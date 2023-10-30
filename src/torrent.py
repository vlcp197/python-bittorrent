from . import bencoding
from hashlib import sha1
from collections import namedtuple
from typing import Union
import os

# Represents the files within the torrent (i.e. the files to write to disk)
TorrentFile = namedtuple('TorrentFile', ['name', 'length'])


class Torrent:
    """
        Wrapper around the bencoded data with utility functions.
    """

    def __init__(self, filename: Union[str, bytes, os.PathLike]):
        self.filename = filename
        self.files: list = []

        with open(self.filename, 'rb') as f:
            meta_info = f.read()
            self.meta_info = bencoding.Decoder(meta_info).decode_data()
            info = bencoding.Encoder(self.meta_info[b'info']).encode_data()
            self.info_hash = sha1(info).digest()
            self._identify_files()

    def _identify_files(self):
        """
            Identifies if the file is multi-file or not.
        """
        if self.multi_file:
            raise RuntimeError("Multi-file torrents is not supported")
        self.files.append(
            TorrentFile(
                self.meta_info[b'info'][b'name'].decode('utf-8'),
                self.meta_info[b'info'][b'length']))

    @property
    def announce(self) -> str:
        """
            Returns the announce URL which is a web address that
            BitTorrent client uses to communicate with a
            BitTorrent Tracker
            e.g. http://tracker.example.com/announce
        """
        return self.meta_info[b'announce'].decode('utf-8')

    @property
    def multi_file(self) -> bool:
        """
            Checks if the torrent contains multiple files
        """
        return b'files' in self.meta_info[b'info']

    @property
    def piece_length(self) -> int:
        """
            Get the length in bytes for each piece
        """
        return self.meta_info[b'info'][b'piece length']

    @property
    def total_size(self) -> int:
        """
            The total size in bytes for all the files in
            this torrent.
        """
        if self.multi_file:
            raise RuntimeError('Multi-file torrents is not supported!')
        return self.files[0].length

    @property
    def pieces(self):
        """
            String representing all pieces SHA1 hashes.
        """
        data = self.meta_info[b'info'][b'pieces']
        pieces = []
        offset = 0
        length = len(data)

        while offset < length:
            pieces.append(data[offset:offset + 20])
            offset += 20
        return pieces

    @property
    def output_file(self):
        return self.meta_info[b'info'][b'name'].decode('utf-8')

    def __str__(self):
        return f"""
                    Filename: {self.meta_info[b'info'][b'name']}
                    File length: {self.meta_info[b'info'][b'length']}
                    Announce URL: {self.meta_info[b'announce']}
                    Hash: {self.info_hash}
                """
