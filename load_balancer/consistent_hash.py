import hashlib


class ConsistentHash:

    def __init__(self):
        self.num_slots = 8192
        self.virtual_servers = 100
        self.ring = [None] * self.num_slots
        self.server_count = 0

    def _hash_to_slot(self, value):
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.num_slots

    def request_hash(self, request_id):
        return self._hash_to_slot(f"request:{request_id}")

    def virtual_server_hash(self, server_id, virtual_id):
        return self._hash_to_slot(f"server:{server_id}:virtual:{virtual_id}")

    def add_server(self, server_id):
        for virtual_id in range(self.virtual_servers):
            slot = self.virtual_server_hash(server_id, virtual_id)
            while self.ring[slot] is not None:
                slot = (slot + 1) % self.num_slots
            self.ring[slot] = (server_id, virtual_id)
        self.server_count += 1

    def get_server(self, request_id):
        slot = self.request_hash(request_id)

        if self.server_count == 0:
            raise RuntimeError("No servers available in hash ring")

        while self.ring[slot] is None:
            slot = (slot + 1) % self.num_slots

        return self.ring[slot][0]

    def remove_server(self, server_id):
        removed = False
        for slot in range(self.num_slots):
            entry = self.ring[slot]
            if entry is None:
                continue
            if entry[0] == server_id:
                self.ring[slot] = None
                removed = True

        if removed:
            self.server_count -= 1
    
    
if __name__ == "__main__":
    ch = ConsistentHash()

    ch.add_server(1)
    ch.add_server(2)
    ch.add_server(3)

    print("\nTesting request routing:\n")

    for request in range(1, 11):
        server = ch.get_server(request)
        print(f"Request {request} → Server {server}")

    for i in range(ch.num_slots):
        if ch.ring[i] is not None:
            print(f"Slot {i}: {ch.ring[i]}")
