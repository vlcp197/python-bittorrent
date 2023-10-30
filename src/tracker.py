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
        peers = ", ".join([x for (x, _) in self.peers])
        return f"""
                    incomplete: {self.incomplete},
                    complete: {self.complete},
                    interval: {self.interval},
                    peers: {peers}
                """

    @property
    def failure(self):
        """
            If this response was a failed response
            this is the error message to why the
            tracker request failed.

            If no error occurred this will be None.
        """
        if b'failure reason' in self.response:
            return self.response[b'failure reason'].decode('utf-8')

        return None

    @property
    def interval(self) -> int:
        """
            Interval in seconds that the client should wait
            sending periodic requests to the tracker.

        """
        return self.response.get(b'interval', 0)

    @property
    def complete(self) -> int:
        """
            Number of peers with the entire file, the seeders.
        """
        return self.response.get(b'complete', 0)

    @property
    def incomplete(self):
        """
            Number of non-seeder peers, the leechers.
        """
        return self.response.get(b'incomplete', 0)

    @property
    def peers(self):
        """
            A list of tuples for each peer structrured as
            (ip, port).
        """
        # The BitTorrent specification specifies two types of responses.
        # One where the peers field is a list of dictionaries and one
        # where all the peers are encoded in a single string.
        peers = self.response[b'peers']
        if type(peers) is list:
            logging.debug('Dictionary model peers are returned by tracker')
            raise NotImplementedError()
        else:
            logging.debug('Binary model peers are returned by tracker')
            peers = [peers[i:i+6] for i in range(0, len(peers), 6)]

        return [(socket.inet_ntoa(p[:4]), _decode_port(p[:4]))
                for p in peers]

