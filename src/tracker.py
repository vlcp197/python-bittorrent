from . import bencoding
import aiohttp
import random
import logging
import socket
from struct import unpack
from urllib.parse import urlencode


class TrackerReponse:
    """

    """

    def __init__(self, response: dict):
        self.response = response

    def __str__(self):
        return

    def failure(self):
        return

    def interval(self):
        return

    def complete(self):
        return

    def incomplete(self):
        return

    def peers(self):
        return
