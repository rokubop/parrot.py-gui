# From https://stackoverflow.com/a/31736883
import sys

from config.config import IS_WINDOWS

if (IS_WINDOWS == True):
    import msvcrt
else:
    import select
    import termios

# Without a terminal there are no keys to poll, and changing the settings of a
# redirected stdin raises. Training from a script or a CI runner lands here.
def stdin_is_interactive():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False

# Courtesy from pokeyrule (https://github.com/pokey)
class KeyPoller():
    def __enter__(self):
        self.interactive = stdin_is_interactive()
        if (IS_WINDOWS == False and self.interactive == True):
            # Save the terminal settings
            self.fd = sys.stdin.fileno()
            self.new_term = termios.tcgetattr(self.fd)
            self.old_term = termios.tcgetattr(self.fd)

            # New terminal setting unbuffered
            self.new_term[3] = (self.new_term[3] & ~termios.ICANON & ~termios.ECHO)
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.new_term)

        return self

    def __exit__(self, type, value, traceback):
        if(IS_WINDOWS == False and self.interactive == True ):
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)

    def poll(self):
        if( self.interactive == False ):
            return None

        if( IS_WINDOWS == True ):
            if( msvcrt.kbhit() ):
                ch = msvcrt.getch()
                if ch == b'\xe0' or ch == b'\000':
                    ch = msvcrt.getch()
                return ch.decode()
        else:
            dr,dw,de = select.select([sys.stdin], [], [], 0)
            if not dr == []:
                return sys.stdin.read(1)
        return None
