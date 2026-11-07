"""Every word the app teaches with, in one place.

One section per tab. A section's topics arrive with the features they
explain, each holding one idea, so any screen can show just the ones it needs
and the About page shows them all.

Copy only. No Qt, so anything may import it.
"""


def tab(key, title):
    return dict(key=key, title=title)


TABS = (
    tab("overview", "Overview"),
    tab("sounds", "Sounds"),
    tab("models", "Models"),
    tab("integrations", "Integrations"),
    tab("program", "About"),
)
