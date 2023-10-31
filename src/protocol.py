import asyncio
import logging
import struct
from asyncio import Queue
from concurrent.futures import CancelledError
import bitstring

REQUEST_SIZE = 2**14


class ProtocolError(BaseException):
    pass


class PeerConnection:
    """
        A peer connection used to download and upload pieces

        The peer connection will consume one availabe peer from the given
        queue.
        Based on the peer details the PeerConnection will try to open a
        connection and perform a BitTorrent handshake.

        After a successful handshake, the PeerConnection will be in a 'choked'
        state, not allowed to request any data from the remote peer. After
        sending an interested message the PeerConnection will be waiting to get
        'unchocked'.

        Once the remote peer unchoked us, we can start requesting pieces.
        The PeerConnection will continue to request pieces for as long as
        there are pieces left to request, or until the remote peer disconnects.

        If the connection with a remote peer drops, the PeerConnection will
        consume the next available peer from off the queue and try to connect
        to that one instead.
    """

    def __init__(self,
                 queue: Queue,
                 info_hash,
                 peer_id,
                 piece_manager,
                 on_block_cb=None):
        """
            Constructs a PeerConnection and add it to the asyncio event-loop.

            Use 'stop' to abort this connection and any subsequent connection
            attempts

            Params:
                queue: The async Queue containing available peers
                info_hash: The SHA1 hash for the meta-data's info
                peer_id: Our peer ID used to identify ourselves
                piece_manager: The manager responsible to determine
                               which pieces to request
                on_block_cb: The callback function to call when a
                             block is received from the peer.
        """
        self.my_state = []
        self.peer_state = []
        self.queue = queue
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.remote_id = None
        self.writer = None
        self.reader = None
        self.piece_manager = piece_manager
        self.on_block_cb = on_block_cb
        self.future = asyncio.ensure_future(self._start())

    async def _start(self):
        while 'stopped' not in self.my_state:
            ip, port = await self.queue.get()
            logging.info(f'Got assigned peer with: {ip}')

            try:
                self.reader, self.writer = await asyncio.open_connection(
                    ip, port
                )
                logging.info(f'Connection to the peer: {ip}')

                buffer = await self._handshake()

                self.my_state.append('chocked')

                await self._send_interested()
                self.my_state.append('interested')

                async for message in PeerStreamIterator(self.reader, buffer):
                    is_bitfield = isinstance(message, BitField)
                    is_interested = isinstance(message, Interested)
                    is_notinterested = isinstance(message, NotInterested)
                    is_choke = isinstance(message, Choke)
                    is_unchoke = isinstance(message, Unchoke)
                    is_have = isinstance(message, Have)
                    is_keepalive = isinstance(message, KeepAlive)
                    is_piece = isinstance(message, Piece)
                    is_request = isinstance(message, Request)
                    is_cancel = isinstance(message, Cancel)

                    if 'stopped' in self.my_state:
                        break
                    if is_bitfield:
                        self.piece_manager.add_peer(self.remote_id,
                                                    message.bitfield)
                    elif is_interested:
                        self.peer_state.append('interested')
                    elif is_notinterested:
                        if 'interested' in self.peer_state:
                            self.peer_state.remove('interested')
                    elif is_choke:
                        self.my_state.append('choked')
                    elif is_unchoke:
                        if 'choked' in self.my_state:
                            self.my_state.remove('choked')
                    elif is_have:
                        self.piece_manager.update_peer(self.remote_id,
                                                       message.index)
                    elif is_keepalive:
                        pass
                    elif is_piece:
                        self.my_state.remove('pending_request')
                        self.on_block_cb(
                            peer_id=self.remote_id,
                            piece_index=message.index,
                            block_offset=message.begin,
                            data=message.block)
                    elif is_request:
                        logging.info('Ignoring the received Request message.')
                    elif is_cancel:
                        logging.info('Ignoring the received Cancel message.')

                    choked_not_in = 'choked' not in self.my_state
                    interested_in = 'interested' in self.my_state
                    pending_request_not_in = (
                        'pending_request' not in self.my_state)

                    if (choked_not_in and interested_in and
                            pending_request_not_in):

                        self.my_state.append('pending_request')
                        await self._request_piece()

            except ProtocolError:
                logging.exception('Protocol error')
            except (ConnectionRefusedError, TimeoutError):
                logging.exception('Unable to connect to peer')
            except (ConnectionResetError, CancelledError):
                logging.exception('Connection closed')
            except Exception as e:
                logging.exception('An error occurred')
                self.cancel()
                raise e
            self.cancel()

    def cancel(self):
        """
            Sends the cancel message to the remote peer and closes the
            connection.
        """
        logging.info(f'Closing peer {self.remote_id}')
        if not self.future.done():
            self.future.cancel()
        if self.writer:
            self.writer.close()

        self.queue.task_done()

    def stop(self):
        """
            Stop this connection from the current peer (if a connection exist)
            and from connecting to any new peer.
        """
        self.my_state.append('stopped')
        if not self.future.done():
            self.future.cancel()

    async def _request_piece(self):
        block = self.piece_manager.next_request(self.remote_id)
        if block:
            message = Request(block.piece,
                              block.offset,
                              block.length).encode()
            logging.debug(f"""
                            Requesting block {block.piece}
                            for piece {block.offset}
                            of {block.length}
                            bytes from peer {self.remote_id}
                           """)
            self.writer.write(message)
            await self.writer.drain()

    async def _handshake(self):
        """
            Send the initial handshake to the remote peer and wait for the peer
            to respond with its handshake.
        """
        self.writer.write(Handshake(self.info_hash, self.peer_id).encode())
        await self.writer.drain()

        buf = b''
        tries = 1
        while len(buf) < Handshake.length and tries < 10:
            tries += 1
            buf = await self.reader.read(PeerStreamIterator.CHUNK_SIZE)

        response = Handshake.decode(buf[:Handshake.length])
        if not response:
            raise ProtocolError('Unable receive and parse a handshake')
        if not response.info_hash == self.info_hash:
            raise ProtocolError('Handshake with invalid info_hash')

        self.remote_id = response.peer_id
        logging.info('Handshake with peer was successful')

        return buf[Handshake.length:]

    async def _send_interested(self):
        message = Interested()
        logging.debug(f'Sending message: {message}')
        self.writer.write(message.encode())
        await self.writer.drain()


class PeerStreamIterator:
    CHUNK_SIZE = 10*1024

    def __init__(self):
        ...

    async def __aiter__(self):
        ...

    async def __anext__(self):
        ...

    def parse(self):
        ...


class PeerMessage:
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOTINTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7
    CANCEL = 8
    PORT = 9
    HANDSHAKE = None
    KEEPALIVE = None

    def encode(self) -> bytes:
        ...

    @classmethod
    def decode(cls, data: bytes):
        ...


class Handshake(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self) -> bytes:
        ...

    @classmethod
    def decode(cls, data: bytes):
        ...


class KeepAlive(PeerMessage):
    def __str__(self):
        ...


class BitField(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self) -> bytes:
        ...

    @classmethod
    def decode(cls, data: bytes):
        ...


class Interested(PeerMessage):
    def __str__(self):
        ...

    def encode(self) -> bytes:
        ...


class NotInterested(PeerMessage):
    def __str__(self):
        ...


class Choke(PeerMessage):
    def __str__(self):
        ...


class Unchoke(PeerMessage):
    def __str__(self):
        ...


class Have(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self):
        ...

    @classmethod
    def decode(cls):
        ...


class Request(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self):
        ...

    @classmethod
    def decode(cls):
        ...


class Piece(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self):
        ...

    @classmethod
    def decode(cls):
        ...


class Cancel(PeerMessage):
    def __init__(self):
        ...

    def __str__(self):
        ...

    def encode(self):
        ...

    @classmethod
    def decode(cls):
        ...
