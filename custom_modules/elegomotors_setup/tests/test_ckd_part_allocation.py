# -*- coding: utf-8 -*-
"""Plain-Python tests (no database) for the rule that ties a receipt move to
one of several PO lines that can take it, e.g. a part shared by two CKD kits."""
from odoo.tests.common import BaseCase, tagged

from ..models.ckd_part_allocation import choose_candidate


def _allocate(rooms, quantities):
    """What the receipt does move by move: each move goes to a candidate and
    takes its quantity out of that candidate's room."""
    rooms = dict(rooms)
    chosen = []
    for qty in quantities:
        key = choose_candidate(list(rooms.items()), qty)
        chosen.append(key)
        rooms[key] -= qty
    return chosen


@tagged('post_install', '-at_install')
class TestChooseCandidate(BaseCase):

    def test_nothing_to_choose_from(self):
        self.assertIsNone(choose_candidate([], 5.0))

    def test_a_single_candidate_takes_every_move_even_without_room(self):
        self.assertEqual(choose_candidate([('a', 10.0)], 4.0), 'a')
        self.assertEqual(choose_candidate([('a', 0.0)], 4.0), 'a')
        self.assertEqual(choose_candidate([('a', -2.0)], 4.0), 'a')

    def test_the_candidate_with_exactly_the_quantity_wins_over_order(self):
        self.assertEqual(choose_candidate([('kit_a', 3.0), ('kit_b', 4.0)], 4.0), 'kit_b')
        self.assertEqual(choose_candidate([('kit_a', 3.0), ('kit_b', 4.0)], 3.0), 'kit_a')

    def test_equal_rooms_take_the_first_one(self):
        self.assertEqual(choose_candidate([('kit_a', 5.0), ('kit_b', 5.0)], 5.0), 'kit_a')

    def test_without_an_exact_fit_the_first_with_room_takes_it(self):
        self.assertEqual(choose_candidate([('kit_a', 0.0), ('kit_b', 6.0)], 2.0), 'kit_b')
        self.assertEqual(choose_candidate([('kit_a', 8.0), ('kit_b', 6.0)], 2.0), 'kit_a')

    def test_with_no_room_anywhere_the_first_candidate_takes_it(self):
        self.assertEqual(choose_candidate([('kit_a', 0.0), ('kit_b', -2.0)], 3.0), 'kit_a')

    def test_a_rounding_difference_is_still_an_exact_fit(self):
        self.assertEqual(
            choose_candidate([('kit_a', 5.0), ('kit_b', 2.9999999)], 3.0), 'kit_b')

    def test_two_kits_sharing_a_part_get_a_move_each(self):
        # Kit A x3 and Kit B x4 both need the part: moves of 3 and 4
        self.assertEqual(_allocate({'kit_a': 3.0, 'kit_b': 4.0}, [3.0, 4.0]), ['kit_a', 'kit_b'])

    def test_equal_kits_sharing_a_part_get_a_move_each(self):
        self.assertEqual(_allocate({'kit_a': 5.0, 'kit_b': 5.0}, [5.0, 5.0]), ['kit_a', 'kit_b'])

    def test_three_kits_sharing_a_part_get_a_move_each(self):
        self.assertEqual(
            _allocate({'kit_a': 5.0, 'kit_b': 5.0, 'kit_c': 4.0}, [5.0, 5.0, 4.0]),
            ['kit_a', 'kit_b', 'kit_c'],
        )

    def test_a_part_that_arrives_short_still_goes_to_the_kit_waiting_for_it(self):
        # an earlier receipt brought 2 of each kit's part: 1 and 2 are still to come
        self.assertEqual(_allocate({'kit_a': 1.0, 'kit_b': 2.0}, [1.0, 2.0]), ['kit_a', 'kit_b'])

    def test_a_kit_that_is_complete_is_skipped(self):
        # kit A already got all it needs, so the move of 4 is kit B's
        self.assertEqual(_allocate({'kit_a': 0.0, 'kit_b': 4.0}, [4.0]), ['kit_b'])
