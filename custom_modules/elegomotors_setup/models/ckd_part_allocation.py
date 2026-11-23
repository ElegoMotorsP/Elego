# -*- coding: utf-8 -*-
"""Which PO line a receipt move belongs to when SEVERAL lines of one PO can
take it (no Odoo imports, so it is easy to test on its own).

Two CKD kits on one PO usually share parts: Kit A x3 and Kit B x4 both need a
front fender, so the receipt has two front-fender moves (3 and 4). The move has
to be tied to the kit line it is for. Choosing "the first line that has this
product" ties both moves to Kit A, so Odoo then sees two identical moves and
merges them (demand 7, but Received 3), and Kit B never sees its fenders.
"""


def choose_candidate(candidates, qty, rounding=0.01):
    """The key of the candidate a move of `qty` should be tied to.

    `candidates` is a sequence of (key, room), in PO order: `room` is how much
    of the part that candidate still has to receive, not counting this move
    (ordered, less what validated receipts brought in, less what the other
    moves of the same receipt already cover).

    A candidate whose room is exactly `qty` is the one this move was made for.
    Failing that, the first candidate that still has room takes it. When none
    has room (more than was ordered, or a line added by hand) it goes to the
    first candidate, which is what always happened before.

    Returns None when there are no candidates."""
    candidates = list(candidates)
    if not candidates:
        return None
    for key, room in candidates:
        if room >= rounding and abs(room - qty) < rounding:
            return key
    for key, room in candidates:
        if room >= rounding:
            return key
    return candidates[0][0]
