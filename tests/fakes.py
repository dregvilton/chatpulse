"""In-memory replacements for external services in offline tests."""

class FakeKeyring:
    def __init__(self):
        self.entries = {}
    def get_password(self, service, username):
        return self.entries.get((service, username))
    def set_password(self, service, username, password):
        self.entries[(service, username)] = password
    def delete_password(self, service, username):
        del self.entries[(service, username)]
