from src.protocol import PeerConnection, REQUEST_SIZE
from src.tracker import Tracker
import asyncio
from asyncio import Queue
import logging
import math
import os
import time
from collections import namedtuple, defaultdict
from hashlib import sha1


MAX_PEER_CONNECTIONS = 40


class TorrentClient:
    """

    """
    def __init__(self, torrent):
        self.tracker = Tracker(torrent)
        self.available_peers = Queue()
        self.peers = []
        self.piece_manager = PieceManager(torrent)
        self.abort = False

    async def start(self):
        """

        """
        self.peers = [PeerConnection(self.available_peers,
                                     self.tracker.torrent.info_hash,
                                     self.tracker.peer_id,
                                     self.piece_manager,
                                     self._on_block_retrieved)
                      for _ in range(MAX_PEER_CONNECTIONS)]

        # The time we last made an announce call (timestamp)
        previous = None
        # Default interval between announce calls (in seconds)
        interval = 30*60

        while True:
            if self.piece_manager.complete:
                logging.info('Torrent fully donwloaded!')
                break
            if self.abort:
                logging.info('Aborting download...')
                break
            
            current = time.time()
            if (not previous) or (previous + interval < current):
                response = await self.tracker.connect(
                    first=previous if previous else False,
                    uploaded=self.piece_manager.bytes_uploaded,
                    downloaded=self.piece_manager.bytes_downloaded)

                if response:
                    previous = current
                    interval = response.interval
                    self._empty_queue()
                    for peer in response.peers:
                        self.available_peers.put_nowait(peer)
            else:
                await asyncio.sleep(5)
        self.stop()

    def _empty_queue(self):
        while not self.available_peers.empty():
            self.available_peers.get_nowait()

    def stop(self):
        """

        """
        self.abort = True
        for peer in self.peers:
            peer.stop()
        self.piece_manager.close()
        self.tracker.close()

    def _on_block_retrieved(self, peer_id, piece_index, block_offset, data):
        """

        """
        self.piece_manager.block_received(
            peer_id=peer_id, 
            piece_index=piece_index,
            block_offset=block_offset,
            data=data
        )


class Block:
    """

    """
    Missing = 0
    Pending = 1
    Retrieved = 2

    def __init__(self, piece: int, offset: int, length: int):
        self.piece = piece,
        self.offset = offset,
        self.length = length,
        self.status = Block.Missing,
        self.data = None


class Piece:
    """

    """
    def __init__(self, index: int, blocks: [], hash_value):
        self.index = index
        self.blocks = blocks
        self.hash = hash_value

    def reset(self):
        """

        """

        for block in self.blocks:
            block.status = Block.Missing

    def next_request(self):
        """

        """
        missing = [b for b in self.blocks if b.status is Block.Missing] 

        if missing:
            missing[0].status = Block.Pending
            return missing[0]
        return None

    def block_received(self, offset: int, data: bytes):
        """

        """
        matches = [b for b in self.blocks if b.offset == offset]
        block = matches[0] if matches else None

        if block:
            block.status = Block.Retrieved
            block.data = data 
        else:
            logging.warning(
                f'Trying to complete a non-existing block {offset}')

    def is_complete(self) -> bool:
        """

        """
        blocks = [b for b in self.blocks
                  if b.status is not Block.Retrieved]
        return len(blocks) == 0

    def is_hash_matching(self):
        """

        """
        piece_hash = sha1(self.data).digest()
        return self.hash == piece_hash

    @property
    def data(self):
        """

        """
        retrieved = sorted(self.blocks, key=lambda b: b.offset)
        blocks_data = [b.data for b in retrieved]
        return b''.join(blocks_data)


PendingRequest = namedtuple('PendingRequest', ['block', 'added'])


class PieceManager:
    """

    """

    def __init__(self, torrent):
        self.torrent = torrent
        self.peers = {}
        self.pending_blocks = []
        self.missing_pieces = []
        self.ongoing_pieces = []
        self.have_pieces = []
        self.max_pending_time = 300 * 1000
        self.missing_pieces = self._initiate_pieces()
        self.total_pieces = len(torrent.pieces)
        self.fd = os.open(self.torrent.output_file, os.O_RDWR | os.O_CREAT)

    def _initiate_pieces(self) -> [Piece]:
        """

        """
        torrent = self.torrent
        pieces = []
        total_pieces = len(torrent.pieces)
        std_piece_blocks = math.ceil(torrent.piece_length / REQUEST_SIZE)

        for index, hash_value in enumerate(torrent.pieces):

            if index < (total_pieces - 1):
                blocks = [Block(index, offset * REQUEST_SIZE, REQUEST_SIZE)
                          for offset in range(std_piece_blocks)]
            else:
                last_length = torrent.total_size % torrent.piece_length
                num_blocks = math.ceil(last_length / REQUEST_SIZE)
                blocks = [Block(index, offset * REQUEST_SIZE, REQUEST_SIZE)
                          for offset in range(num_blocks)]

                if last_length % REQUEST_SIZE > 0:
                    last_block = blocks[-1]
                    last_block.length = last_length % REQUEST_SIZE
                    blocks[-1] = last_block
            pieces.append(Piece(index, blocks, hash_value))
        return pieces

    def close(self):
        """

        """
        if self.id:
            os.close(self.fd)

    @property
    def complete(self):
        """

        """
        return len(self.have_pieces) == self.total_pieces

    @property
    def bytes_downloaded(self) -> int:
        """

        """
        return len(self.have_pieces) * self.torrent.piece_length

    @property
    def bytes_uploaded(self):
        """

        """
        return 0

    def add_peer(self, peer_id, bitfield):
        """

        """
        self.peers[peer_id] = bitfield

    def update_peer(self, peer_id):
        """

        """
        if peer_id in self.peers:
            del self.peers[peer_id]

    def remove_peer(self, peer_id):
        """

        """
        if peer_id in self.peers:
            del self.peers[peer_id]

    def next_request(self, peer_id) -> Block:
        """

        """

        if peer_id not in self.peers:
            return None

        block = self._expired_requests(peer_id)
        if not block:
            block = self._next_ongoing(peer_id)
            if not block:
                block = self._get_rarest_piece(peer_id).next_request()
        return block

    def block_received(self, peer_id, piece_index, block_offset, data):
        """

        """
        logging.debug(f'Received block {block_offset} for piece {piece_index}'
                      f'from peer {peer_id}: ')

        for index, request in enumerate(self.pending_blocks):
            if request.block.piece == piece_index and \
               request.block.offset == block_offset:
                del self.pending_blocks[index]
                break

        pieces = [p for p in self.ongoing_pieces if p.index == piece_index]
        piece = pieces[0] if pieces else None
        if piece:
            piece.block_received(block_offset, data)
            if piece.is_complete():
                self._write(piece)
                self.ongoing_pieces.remove(piece)
                self.have_pieces.append(piece)
                complete = (self.total_pieces -
                            len(self.missing_pieces) -
                            len(self.ongoing_pieces))
                per = (complete / self.total_pieces) * 100
                logging.info(
                    f'{complete} / {self.total_pieces}'
                    f'pieces downloaded {per:.3f} %'
                )
            else:
                logging.info(f'Discarding corrupt piece {piece.index}')
                piece.reset()
        else:
            logging.warning('Trying to update piece that is not ongoing.')

    def _expired_requests(self, peer_id) -> Block:
        """

        """
        current = int(round(time.time() * 1000))
        for request in self.pending_blocks:
            if self.peers[peer_id][request.block.piece]:
                if request.added + self.max_pending_time < current:
                    logging.info(f'Re-requesting block {request.block.offset}'
                                 f'for piece {request.block.piece}')

                    request.added = current
                    return request.block
        return None

    def _next_ongoing(self, peer_id) -> Block:
        """

        """
        for piece in self.ongoing_pieces:
            if self.peers[peer_id][piece.index]:

                block = piece.next_request()
                if block:
                    self.pending_blocks.append(
                        PendingRequest(block, int(round(time.time() * 1000))))
                    return block
        return None

    def _get_rarest_piece(self, peer_id):
        """

        """
        piece_count = defaultdict(int)
        for piece in self.missing_pieces:
            if not self.peers[peer_id][piece.index]:
                continue
            for p in self.peers:
                if self.peers[p][piece.index]:
                    piece_count[piece] += 1

        rarest_piece = min(piece_count, key=lambda p: piece_count[p])
        self.missing_pieces.remove(rarest_piece)
        self.ongoing_pieces.append(rarest_piece)
        return rarest_piece

    def _next_missing(self, peer_id) -> Block:
        """

        """
        for index, piece in enumerate(self.missing_pieces):
            if self.peers[peer_id][piece.index]:
                piece = self.missing_pieces.pop(index)
                self.ongoing_pieces.append(piece)
                return piece.next_request()
        return None

    def _write(self, piece):
        """

        """
        pos = piece.index * self.torrent.piece_length
        os.lseek(self.fd, pos, os.SEEK_SET)
        os.write(self.fd, piece.data)
