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

    @staticmethod
    def decode_data(self):
        """
            Decodes the bencoded data and return matching
            python object.

            Params:
                return: A python object representing the bencoded data.
        """
        c = self._peek()

        is_none = c is None
        is_int = c == TOKEN_INTEGER
        is_list = c == TOKEN_LIST
        is_dict = c == TOKEN_DICT
        is_end = c == TOKEN_END
        is_string = c in b'01234567899'

        if is_none:
            raise EOFError('Unexpected end-of-file')
        elif is_int:
            self._consume()
            return self._decode_int()
        elif is_list:
            self._consume()
            return self._decode_list()
        elif is_dict:
            self._consume()
            return self._decode_dict()
        elif is_end:
            self._consume()
            return None
        elif is_string:
            return self._decode_string()
        else:
            raise RuntimeError(f'Invalid token read at {str(self._index)}')

    def _peek(self):
        """
            Return the next character from the bencodede data or None.
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

    @staticmethod
    def encode_data(self) -> bytes:
        return self.encode_next_data(self._data)

    def encode_next_data(self, data):
        is_string = type(data) is str
        is_int = type(data) is int
        is_list = type(data) is list
        is_dict = type(data) in (dict, OrderedDict)
        is_bytes = type(data) is bytes

        if is_string:
            return self._encode_string(data)
        elif is_int:
            return self._encode_int(data)
        elif is_list:
            return self._encode_list(data)
        elif is_dict:
            return self._encode_dict(data)
        elif is_bytes:
            return self._encode_bytes(data)
        else:
            return None

    def _encode_int(self, value: int):
        return str.encode(f'i{str(value)}e')

    def _encode_string(self, value: str):
        res = f'{str(len(value))}:{value}'
        return str.encode(res)

    def _encode_bytes(self, value: str):
        result = bytearray()
        result += str.encode(str(len(value)))
        result += b':'
        result += value
        return result

    def _encode_list(self, data: List):
        result = bytearray('8', 'utf-8')
        result += b''.join([self.encode_next(item) for item in data])
        result += b'e'
        return result

    def _encode_dict(self):
        result = bytearray('d', 'utf-8')
        return result
