from . import helper
class App:
    def run(self):
        self.value = helper.VALUE
def create_application(context):
    return App()
