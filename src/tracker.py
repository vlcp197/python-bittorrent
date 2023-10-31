from . import bencoding
import aiohttp
import random
import logging
import socket
from struct import unpack
from urllib.parse import urlencode


class TrackerResponse:
    """
        The response from the tracker after a successful
        connection to the trackers announce URL.

        Even though the connection was successful from a
        network point of view, the tracker might have
        returned an error (stated in the "failure"
        property)
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

        return [(socket.inet_ntoa(p[:4]), Tracker.decode_port(p[:4]))
                for p in peers]


class Tracker:
    """
        Represents the connection to a tracker
        for a given Torrent that is either
        under download or seeding state.
    """

    def __init__(self, torrent):
        self.torrent = torrent
        self.peer_id = self._calculate_peer_id(self)
        self.http_client = aiohttp.ClientSession()

    async def connect(self,
                      first: bool = None,
                      uploaded: int = 0,
                      downloaded: int = 0):
        """
            Makes the announce call to the tracker to update
            with our statistics as well as get a list of
            available peers to connect to.

            If the call was successful, the list of peers will
            be updated as a result of calling this function.

            Params:
                first: Whether or not this is the first announce call.
                uploaded: The total number of bytes uploaded.
                downloaded: The total number of bytes downloaded.
        """
        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': 6889,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': self.torrent.total_size - downloaded,
            'compact': 1}
        if first:
            params['event'] = 'started'

        url = self.torrent.announce + '?' + urlencode(params)
        logging.info('Connecting to tracker at: ' + url)

        async with self.http_client.get(url) as response:
            if not response.status == 200:
                raise ConnectionError(
                    f'Unable to connect to tracker: \
                        status code {response.status}')
            data = await response.read()
            self.raise_for_error(data)
            return TrackerResponse(bencoding.Decoder(data).decode_data())

    def close(self):
        self.http_client.close()

    def raise_for_error(self, tracker_response):
        """
            Fix to detect errors by tracker even when the
            response has a status code of 200.
        """
        try:
            message = tracker_response.decode("utf-8")
            if "failure" in message:
                raise ConnectionError(
                    f'Unable to connect to tracker: {message}')
        except UnicodeDecodeError:
            pass

    def _construct_tracker_parameters(self):
        """
            Constructs the URL parameters used when issuing
            the announce call to the tracker.
        """
        return {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': 6889,
            'uploaded': 0,
            'downloaded': 0,
            'left': 0,
            'compact': 1}

    def _calculate_peer_id():
        """
            Calculate and return a unique peer ID.

            The 'peer id' is a 20 byte long identifier.
            This implementation use the Azureus style
            '-PC1000-<random-characters>'.
        """
        return '-PC0001-' + ''.join(
            [str(random.randint(0, 9)) for _ in range(12)]
        )

    @staticmethod
    def decode_port(port):
        """
            Converts a 32-bit packed binary port number to int.
        """
        return unpack(">H", port)[0]
