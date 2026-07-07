class ConsistentHash:

    def __init__(self):
        self.num_slots = 512
        self.virtual_servers = 9
        self.ring = [None] * self.num_slots

    def request_hash(self, request_id):
        return (request_id * request_id + 2 * request_id + 17) % self.num_slots

    def virtual_server_hash(self, server_id, virtual_id):
        return (
            server_id * server_id
            + virtual_id * virtual_id
            + 2 * virtual_id
            + 25
        ) % self.num_slots
    def add_server(self, server_id):
        for virtual_id in range(self.virtual_servers):
            #is the slot empty? if not, we need to find the next available slot
            slot = self.virtual_server_hash(server_id, virtual_id)
            #if not, we need to find the next available slot, move + 1, but we have to check if it occupied already
            while self.ring[slot] is not None:
                slot = (slot + 1) % self.num_slots
            #then we next server is inserted into the next available slot
            self.ring[slot] = (server_id, virtual_id)
            print(f"Server {server_id} Virtual {virtual_id} placed at slot {slot}")
    
    def get_server(self, request_id):
        # Compute request hash and walk clockwise until a server is found.
        slot = self.request_hash(request_id)

        if all(entry is None for entry in self.ring):
            raise RuntimeError("No servers available in hash ring")

        while self.ring[slot] is None:
            # Move clockwise around the ring until we find a populated slot.
            slot = (slot + 1) % self.num_slots

        server_id, virtual_id = self.ring[slot]
        print(f"Request {request_id} " f"mapped to Server {server_id} " f"(Virtual {virtual_id})")
        return self.ring[slot][0]  # return the server_id
    
    def remove_server(self, server_id):
 
        for slot in range(self.num_slots):

        # Skip empty slots
            if self.ring[slot] is None:
             continue

        # Check if this virtual server belongs to the server we're removing
            if self.ring[slot][0] == server_id:
                print(f"Removing Server {server_id} from slot {slot}")
                self.ring[slot] = None
    
    
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
