import json
import os
import socket
import time
import uuid


class CLL1Client:
    """Cliente da A.R.I.S. para comunicacao com o CLL1."""

    def __init__(self, host=None, port=None, timeout=10):
        self.host = host or os.getenv("CLL1_HOST", "192.168.0.106")
        self.port = int(port or os.getenv("CLL1_PORT", "8765"))
        self.timeout = timeout
        self._session_id = str(uuid.uuid4())[:12]

    def _get_token(self):
        token = os.getenv("CLL1_TOKEN")

        if not token:
            raise RuntimeError(
                "CLL1_TOKEN não está definido."
            )

        return token

    def _request(self, payload):
        payload = dict(payload)
        payload["token"] = self._get_token()

        data = json.dumps(
            payload,
            ensure_ascii=False
        ).encode("utf-8")

        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout
        ) as sock:

            sock.sendall(
                len(data).to_bytes(8, "big")
            )

            sock.sendall(data)

            size_data = b""

            while len(size_data) < 8:

                chunk = sock.recv(
                    8 - len(size_data)
                )

                if not chunk:
                    raise ConnectionError(
                        "CLL1 encerrou a conexão."
                    )

                size_data += chunk

            size = int.from_bytes(
                size_data,
                "big"
            )

            if size <= 0 or size > 20 * 1024 * 1024:
                raise RuntimeError(
                    "Resposta inválida do CLL1."
                )

            response = b""

            while len(response) < size:

                chunk = sock.recv(
                    min(
                        65536,
                        size - len(response)
                    )
                )

                if not chunk:
                    raise ConnectionError(
                        "CLL1 encerrou a conexão."
                    )

                response += chunk

        result = json.loads(
            response.decode("utf-8")
        )

        if not result.get("ok"):
            raise RuntimeError(
                f"CLL1 retornou erro: {result}"
            )

        return result

    def ping(self):
        return self._request({
            "type": "admin_ping"
        })

    def status(self):
        return self._request({
            "type": "status"
        })

    def add_memory(
        self,
        content,
        category="general",
        importance=1
    ):
        return self._request({
            "type": "memory_add",
            "content": content,
            "category": category,
            "importance": importance
        })

    def get_memories(self, limit=20):
        return self._request({
            "type": "memory_get",
            "limit": limit
        })

    def search_memories(
        self,
        query,
        limit=20
    ):
        return self._request({
            "type": "memory_search",
            "query": query,
            "limit": limit
        })

    def set_state(self, key, value):
        return self._request({
            "type": "memory_state",
            "key": key,
            "value": value
        })

    def get_state(self, key):
        return self._request({
            "type": "memory_state",
            "key": key,
        })

    def send_message(self, text, source="cll1", user_id="cll1-device"):
        """Envia mensagem ao CLL1 para roteamento."""
        msg_id = str(uuid.uuid4())[:8]
        return self._request({
            "type": "msg",
            "payload": {
                "text": text,
                "source": source,
                "user_id": user_id,
                "session_id": self._session_id,
                "message_id": msg_id,
            },
            "ts": time.time(),
        })

    def sync_push(self, pending, since=""):
        """Envia pendencias de sincronizacao ao CLL1."""
        return self._request({
            "type": "sync_push",
            "pending": pending,
            "since": since,
        })

    def sync_request(self):
        """Requisita sincronizacao do CLL1."""
        return self._request({
            "type": "sync_request",
        })

    def heartbeat_status(self):
        """Heartbeat simplificado para verificar status."""
        return self._request({
            "type": "heartbeat",
            "node_id": "aris-pc",
            "status": "online",
            "pc_status": "online",
            "version": "2.0.0",
        })


if __name__ == "__main__":

    client = CLL1Client()

    print("A.R.I.S. → CLL1")
    print()

    try:

        print("1. Conexão:")
        print(
            json.dumps(
                client.ping(),
                indent=2,
                ensure_ascii=False
            )
        )

        print()
        print("2. Gravando memória:")

        created = client.add_memory(
            "Teste de memória remota da A.R.I.S.",
            category="test",
            importance=5
        )

        print(
            json.dumps(
                created,
                indent=2,
                ensure_ascii=False
            )
        )

        print()
        print("3. Buscando memória:")

        memories = client.search_memories(
            "memória remota"
        )

        print(
            json.dumps(
                memories,
                indent=2,
                ensure_ascii=False
            )
        )

        print()
        print("4. Estado do sistema:")

        client.set_state(
            "aris_connection",
            "online"
        )

        state = client.get_state(
            "aris_connection"
        )

        print(
            json.dumps(
                state,
                indent=2,
                ensure_ascii=False
            )
        )

        print()
        print("TESTE COMPLETO: OK")

    except Exception as e:

        print()
        print(
            f"TESTE FALHOU: {e}"
        )
