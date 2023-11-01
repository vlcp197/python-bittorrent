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
    ...


class Block:
    ...


class Piece:
    ...


class PieceManager:
    ...