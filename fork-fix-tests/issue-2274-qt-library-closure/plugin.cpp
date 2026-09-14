// A plugin that uses two Qt frameworks. Only one of them will be in the payload.
extern "C" void *qtCoreEntry();
extern "C" void *qtQuickEntry();
extern "C" void pluginInit() { qtCoreEntry(); qtQuickEntry(); }
