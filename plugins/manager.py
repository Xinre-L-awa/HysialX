class PluginMeta:
    PluginName: str
    PluginUsage: str
    PluginAuthor: str
    PluginDescription: str

    def __init__(self, Name=None, Usage=None, Author=None, Description=None):
        self.PluginName = Name
        self.PluginUsage = Usage
        self.PluginAuthor = Author
        self.PluginDescription = Description
