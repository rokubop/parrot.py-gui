# From https://stackoverflow.com/a/31736883
import sys

from config.config import IS_WINDOWS

if (IS_WINDOWS == True):
    import msvcrt
else:
    import select
    import termios

def stdin_is_interactive():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):
        return False

# Courtesy from pokeyrule (https://github.com/pokey)
class KeyPoller():
    def __enter__(self):
        # Only posix cares: tcgetattr raises when stdin is not a tty. Windows
        # polls the console, which a redirected stdin does not affect.
        self.can_poll = IS_WINDOWS or stdin_is_interactive()
        if (IS_WINDOWS == False and self.can_poll == True):
            # Save the terminal settings
            self.fd = sys.stdin.fileno()
            self.new_term = termios.tcgetattr(self.fd)
            self.old_term = termios.tcgetattr(self.fd)

            # New terminal setting unbuffered
            self.new_term[3] = (self.new_term[3] & ~termios.ICANON & ~termios.ECHO)
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.new_term)

        return self

    def __exit__(self, type, value, traceback):
        if(IS_WINDOWS == False and self.can_poll == True ):
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)

    def poll(self):
        if( self.can_poll == False ):
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
