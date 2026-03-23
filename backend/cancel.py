# Shared cancellation flag — avoids circular imports
cancelled = False

def reset(): 
    global cancelled
    cancelled = False

def stop():
    global cancelled
    cancelled = True

def is_cancelled():
    return cancelled
