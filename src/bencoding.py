# Bencoding is a data serialization format used in torrent files
# for the Bittorrent protocol.
# Its a simple and efficient way to encode data in a platform-independent way.
# Bencoding suports four differents types of values:
# Strings, integers, lists and dictionaries.
# Exemple of a bencoded value: d4:name4:spam4:info12:length4:1234e .

from collections import OrderedDict
from typing import Union, List, Dict

# Indicates start of integers
TOKEN_INTEGER = b'i'

# Indicates start of lists
TOKEN_LIST = b'l'

# Indicates start of dicts
TOKEN_DICT = b'd'

# Indicates end of lists, dicts and integer values
TOKEN_END = b'e'

# Delimits string length from string data
TOKEN_STRING_SEPARATOR = b':'


class Decoder:
    """
        Class to manage a bencoded sequence of bytes
    """
    def __init__(self, data: bytes):
        if not isinstance(data, bytes):
            raise TypeError(
                "Argument 'data' must be of type 'bytes'")
        self._data = data
        self._index = 0

    def _peek(self):
        """
            Return the next character from the bencodede data or None
        """
        if self._index + 1 >= len(self._data):
            return None
        return self._data[self._index:self._index + 1]

    def _consume(self):
        ...

    def _read(self):
        ...

    def _read_until(self):
        ...

    def _decode_int(self):
        ...

    def _decode_list(self):
        ...

    def _decode_dict(self):
        ...

    def _decode_string(self):
        ...


class Encoder:
    """
        Encodes a python object to a bencoded sequences of bytes.
        Any other type will be simply ignored.
    """
    def __init__(self, data: Union[bytes, str, int, List, Dict]):
        self._data = data

    def _encode_int(self):
        ...

    def _encode_string(self):
        ...

    def _encode_bytes(self):
        ...

    def _encode_list(self):
        ...

    def _encode_dict(self):
        ...
