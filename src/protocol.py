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
    """
        The 'PeerStreamIterator' is an async iterator that continuosly reads
        from the given stream reader and tries to parse valid BitTorrent
        messages from off that stream of bytes.

        If the connection is dropped, something fails the iterator will abort
        by raising the 'StopAsyncIteration' error ending the calling iteration.
    """
    CHUNK_SIZE = 10*1024

    def __init__(self, reader, initial: bytes = None):
        self.reader = reader
        self.buffer = initial if initial else b''

    async def __aiter__(self):
        return self

    async def __anext__(self):
        """
            Read data from the socket. When we have enough data to parse, parse
            it and return the message. Until then keep reading from stream.
        """
        while True:
            try:
                data = await self.reader.read(self.CHUNK_SIZE)
                if data:
                    self.buffer += data
                    message = self.parse()
                    if message:
                        return message
                else:
                    logging.debug('No data read from stream')
                    if self.buffer:
                        message = self.parse()
                        if message:
                            return message
                    raise StopAsyncIteration()
            except ConnectionResetError:
                logging.debug('Connection closed by peer')
                raise StopAsyncIteration()
            except CancelledError:
                raise StopAsyncIteration()
            except StopAsyncIteration as e:
                raise e
            except Exception:
                logging.exception('Error when iterating over stream!')
                raise StopAsyncIteration()
            raise StopAsyncIteration()

    def parse(self):
        """
            Tries to parse protocol messages if there is enough bytes read
            in the buffer.

            Params:
                return: The parsed message, or None if no message could be 
                parsed.
        """
        # Each message is structured as:
        #   <length prefix><message ID><payload>
        #
        # The 'length prefix' is a four byte big-endian value
        # The 'message ID' is a decimal byte
        # The 'payload' is the value of 'length prefix'
        #
        # The message length is not part of the actual length. So another
        # 4 bytes needs to be included when slicing the buffer.
        header_length = 4

        if len(self.buffer) > 4:  # 4 bytes is needed to identify the message
            message_length = struct.unpack('>I', self.buffer[0:4])[0]

            if message_length == 0:
                return KeepAlive()

            if len(self.buffer) >= message_length:
                message_id = struct.unpack('>b', self.buffer[4:5])[0]

                def _consume():
                    """
                        Consume the current message from the read buffer.
                    """
                    self.buffer = self.buffer[header_length + message_length:]

                def _data():
                    """
                        Extract the current message from the read buffer.
                    """
                    return self.buffer[:header_length + message_length]

                if message_id is PeerMessage.BITFIELD:
                    data = _data()
                    _consume()
                    return BitField.decode(data)
                elif message_id is PeerMessage.INTERESTED:
                    _consume()
                    return Interested()
                elif message_id is PeerMessage.NOTINTERESTED:
                    _consume()
                    return NotInterested
                elif message_id is PeerMessage.CHOKE:
                    _consume()
                    return Choke()
                elif message_id is PeerMessage.UNCHOKE:
                    _consume()
                    return Unchoke()
                elif message_id is PeerMessage.HAVE:
                    data = _data()
                    _consume()
                    return Have.decode(data)
                elif message_id is PeerMessage.PIECE:
                    data = _data()
                    _consume()
                    return Piece.decode(data)
                elif message_id is PeerMessage.REQUEST:
                    data = _data()
                    _consume()
                    return Request.decode(data)
                elif message_id is PeerMessage.CANCEL:
                    data = _data()
                    _consume()
                    return Cancel.decode(data)
                else:
                    logging.info('Unsupported message!')
            else:
                logging.debug('Not enough in buffer in order to parse.')

        return None


class PeerMessage:
    """
        Base class to message between two peers.

        All of the remaining messages in the protocol take the from of:
            <length prefix><message ID><payload>

        - The length prefix is a four byte big-endian value.
        - The message ID is a single decimal byte.
        - The payload is message dependent.

        NOTE: The Handshake message is different in layout compared to the
              messages.

        BitTorrent uses Big-Endian (Network Byte Order) for all messages, this
        is declared as the first character being '>' in all pack / unpack calls
        to the Python's "struct" mobile.
    """

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
    HANDSHAKE = None  # Handshake is not really part of the messages
    KEEPALIVE = None  # Keep-alive has no ID according to spec

    def encode(self) -> bytes:
        """
            Encodes this object instance to the raw bytes representing the
            entire message (ready to be transmitted).
        """
        pass

    @classmethod
    def decode(cls, data: bytes):
        """
            Decodes the given BitTorrent message into a instance for the
            implementing type.
        """
        pass


class Handshake(PeerMessage):
    """
        The handshake message is the first message sent and then received from
        a remote peer.

        The messages is always 68 bytes long (for this version of BitTorrent 
        protocol).

        Message format:
            <pstrlen><pstr><reserved><info_hash><peer_id>

        In version 1.0 of the BitTorrent protocol:
            pstrlen = 19
            pstr = "BitTorrent Protocol"

        Thus length is:
            49 + len(pstr) = 68 bytes long.
    """
    length = 49 + 19

    def __init__(self, info_hash: bytes, peer_id: bytes):
        """
            Construct the handshake message
            Params:
                info_hash: The SHA1 hash for the info dict
                peer_id: The unique peer id
        """
        if isinstance(info_hash, str):
            info_hash = info_hash.encode('utf-8')
        if isinstance(peer_id, str):
            peer_id = peer_id.encode('utf-8')
        self.info_hash = info_hash
        self.peer_id = peer_id

    def __str__(self):
        return 'Handshake'

    def encode(self) -> bytes:
        """
            Encodes this object instance to the raw bytes representing the 
            entire message (ready to be transmitted).
        """
        return struct.pack(
            '>B19s8x20s20s',
            19,
            b'BitTorrent protocol',
            self.info_hash,
            self.peer_id)

    @classmethod
    def decode(cls, data: bytes):
        """
            Decodes the BitTorrent given message into a handshake message, if 
            not a valid message, None is returned.
        """
        logging.debug(f'Decoding Handshake of length: {len(data)}')
        if len(data) < (49 + 19):
            return None
        parts = struct.unpack('>B19s8x20s20s', data)
        return cls(info_hash=parts[2], peer_id=parts[3])


class KeepAlive(PeerMessage):
    """
        The Keep-Alive message has no payload and length is set to zero.

        Message format:
            <len=0000>
    """
    def __str__(self):
        return 'KeepAlive'


class BitField(PeerMessage):
    """
        The BitField is a message with variable length where the payload is a
        bit array representing all the bits a peer have (1) or does not have
        (0).

        Message format:
            <len=0001+X><id=5><bitfield>
    """
    def __init__(self, data):
        self.bitfield = bitstring.BitArray(bytes=data)

    def __str__(self):
        return "BitField"

    def encode(self) -> bytes:
        """
            Encodes this object instance to the raw bytes representing the
            entire message (ready to be transmitted).
        """
        bits_length = len(self.bitfield)
        return struct.pack(f'>Ib{str(bits_length)}s',
                           1 + bits_length,
                           PeerMessage.BITFIELD,
                           self.bitfield)

    @classmethod
    def decode(cls, data: bytes):
        message_length = struct.unpack('>I', data[:4])[0]
        logging.debug(f'Decoding BitField of length: {message_length}')

        parts = struct.unpack(f'>Ib{str(message_length - 1)}s', data)
        return cls(parts[2])


class Interested(PeerMessage):
    """
        The interested message is fix length and has no payload other than the
        message identifiers. It is used to notify each other about interest in
        downloading pieces.

        Message format:
            <len=0001><id=2>
    """
    def __str__(self):
        return 'Interested'

    def encode(self) -> bytes:
        """
            Encode this object instance to the raw bytes representing the
            entire message (ready to be transmitted).
        """
        return struct.pack('>Ib',
                           1,
                           PeerMessage.INTERESTED)


class NotInterested(PeerMessage):
    """
        The not interested message is fix length and has no payload other than
        the message identifier. It is used to notify each other that there is 
        no interest to download pieces.

        Message format:
            <len=0001><id=3>
    """
    def __str__(self):
        return 'NotInterested'


class Choke(PeerMessage):
    """
        The choke message is used to tell the other peer to stop send request
        messages until unchoked.

        Message format:
            <len=0001><id=0> 
    """
    def __str__(self):
        return 'Choke'


class Unchoke(PeerMessage):
    """
        Unchoking a peer enables that peer to start requesting pieces from the
        remote peer.

        Message format:
            <len=0001><id=1>
    """
    def __str__(self):
        return 'Unchoke'


class Have(PeerMessage):
    """
        Represents a piece successfully downloaded by the remote peer. The
        piece is a zero based index of the torrents pieces.
    """
    def __init__(self, index: int):
        self.index = index

    def __str__(self):
        return "Have"

    def encode(self):
        return struct.pack('>IbI',
                           5,
                           PeerMessage.HAVE,
                           self.index)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug(f'Decoding Have of length: {len(data)}')
        index = struct.unpack('>IbI', data)[2]
        return cls(index)


class Request(PeerMessage):
    """
        The message used to request a block of a piece (i.e. a partial piece).

        The request size for each block is 2^14 bytes, except the final block
        that might be smaller (since not all pieces might be evenly divided by
        the request size).

        Message format:
            <len=0013><id=6><index><begin><length>
    """
    def __init__(self, index: int, begin: int, length: int = REQUEST_SIZE):
        """
            Constructs the Request message.

            Params:
                index: The zero based piece index.
                begin: The zero based offset within a piece.
                length: The requested length of data (default 2^14).
        """
        self.index = index
        self.begin = begin
        self.length = length

    def __str__(self):
        return "Request"

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           PeerMessage.REQUEST,
                           self.index,
                           self.begin,
                           self.length)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug(f'Decoding Request of length: {len(data)}')
        parts = struct.unpack('>IbIII', data)
        return cls(parts[2], parts[3], parts[4])


class Piece(PeerMessage):
    """
        A block is a part of a piece mentioned in the meta-info. The official
        specification refer to them as pieces as well - which is quite
        confusing.
        The unofficial specification refers to them as block however.

        So this class is named 'Piece' to match a message in the specification
        but really, it represents a 'Block' (which is non-existent in the spec).

        Message format:
            <length prefix><message ID><index><begin><block>
    """

    length = 9

    def __init__(self, index: int, begin: int, block: bytes):
        """
            Constructs the piece message.

            Params:
                index: The zero based piece index
                begin: The zero based offset within a piece.
                block: The block data.
        """
        self.index = index
        self.begin = begin
        self.block = block

    def __str__(self):
        return "Piece"

    def encode(self):
        message_length = Piece.length + len(self.block)
        return struct.pack(f'>IbII{str(len(self.block))}s',
                           message_length,
                           PeerMessage.Piece,
                           self.index,
                           self.begin,
                           self.block)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug(f'Decoding Piece of length: {len(data)}')
        length = struct.unpack('>I', data[:4])[0]
        parts = struct.unpack(f'>IbII{str(length - Piece.length)}s')
        return cls(parts[2], parts[3], parts[4])


class Cancel(PeerMessage):
    """
        The cancel message is used to cancel a previously requested block
        (in fact the message is identical (besides from the id) to the Request
        message).

        Message format:
            <len=0013><id=8><index><begin><length>
    """

    def __init__(self, index, begin, length: int = REQUEST_SIZE):
        self.index = index
        self.begin = begin
        self.length = length

    def __str__(self):
        return "Cancel"

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           PeerMessage.CANCEL,
                           self.index,
                           self.begin,
                           self.length)

    @classmethod
    def decode(cls, data: bytes):
        logging.debug(f'Decoding cancel of length: {len(data)}')
        parts = struct.unpack('>IbIII', data)
        return cls(parts[2], parts[3], parts[4])
