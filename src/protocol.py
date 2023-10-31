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
    def __init__(self):
        ...

    async def _start(self):
        ...

    def cancel(self):
        ...

    def stop(self):
        ...

    async def _request_piece(self):
        ...

    async def _handshake(self):
        ...

    async def _send_interested(self):
        ...


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