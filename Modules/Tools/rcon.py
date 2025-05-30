import asyncio
import struct
from typing import Optional

class RCONError(Exception):
    pass

class RCONClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0

    async def connect(self) -> None:
        """Установка соединения с RCON-сервером"""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout
            )
            await self._authenticate()
        except (asyncio.TimeoutError, ConnectionRefusedError) as e:
            raise RCONError(f"Connection failed: {str(e)}") from e

    async def close(self) -> None:
        """Закрытие соединения"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.writer = None
            self.reader = None

    async def send_command(self, command: str) -> str:
        """Отправка команды на сервер"""
        if not self.writer or not self.reader:
            raise RCONError("Not connected")

        self._request_id += 1
        packet = self._create_packet(2, command)
        
        try:
            self.writer.write(packet)
            await asyncio.wait_for(self.writer.drain(), timeout=self.timeout)
            
            response = await self._read_response(self._request_id)
            return response.strip('\x00')
        except asyncio.TimeoutError as e:
            raise RCONError("Command timed out") from e

    async def _authenticate(self) -> None:
        """Аутентификация на сервере"""
        auth_packet = self._create_packet(3, self.password)
        self.writer.write(auth_packet)
        await self.writer.drain()

        response = await self._read_packet()
        if response['id'] == -1 or response['type'] != 2:
            await self.close()
            raise RCONError("Authentication failed")

    def _create_packet(self, ptype: int, body: str) -> bytes:
        """Создание RCON-пакета"""
        body_bytes = body.encode('utf-8') + b'\x00\x00'
        packet_id = self._request_id
        packet = struct.pack('<3i', 
                            len(body_bytes) + 10,  # Длина пакета
                            packet_id,              # ID запроса
                            ptype)                  # Тип пакета
        packet += body_bytes
        return packet

    async def _read_response(self, expected_id: int) -> str:
        """Чтение ответа от сервера (с обработкой многопакетных ответов)"""
        response = []
        while True:
            packet = await self._read_packet()
            
            if packet['id'] != expected_id:
                raise RCONError("Invalid response ID")
            
            response.append(packet['body'])
            
            # Проверка на завершение пакета (для Source Engine)
            if len(packet['body']) < 4096:
                break
                
        return ''.join(response)

    async def _read_packet(self) -> dict:
        """Чтение и парсинг одного RCON-пакета"""
        try:
            # Чтение длины пакета (4 байта, little-endian)
            size_data = await asyncio.wait_for(
                self.reader.readexactly(4),
                timeout=self.timeout
            )
            size = struct.unpack('<i', size_data)[0]

            # Чтение остальных данных пакета
            packet_data = await asyncio.wait_for(
                self.reader.readexactly(size),
                timeout=self.timeout
            )
        except asyncio.IncompleteReadError as e:
            raise RCONError("Connection lost") from e

        # Распаковка заголовка пакета
        packet_id, ptype = struct.unpack('<2i', packet_data[:8])
        body = packet_data[8:-2].decode('utf-8', errors='replace')
        
        return {
            'id': packet_id,
            'type': ptype,
            'body': body
        }

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()