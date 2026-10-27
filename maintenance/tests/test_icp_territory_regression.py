"""A04: free-form seller territory must not mix country and state levels."""
from copy import deepcopy

from aclad.commands import dispatch
from aclad.models import GateError
from tests.support import StateTest


def criterion(field, values):
    return {'field': field, 'operator': 'in', 'value': values, 'basis': 'hypothesis'}


class IcpTerritoryRegressionTests(StateTest):
    def configure(self, territory, industries=None):
        current = self.store.get('profile', 'current')
        return self.store.put('profile', 'current', {
            'seller': {'territory': territory},
            'partner': {'industries': industries or []},
            'icp': {'exclusions': ['Do not contact public agencies']},
        }, current.revision if current else None)

    def propose(self, country=None, states=None, extra=None):
        criteria = ([] if country is None else [criterion('country', country)])
        criteria += [] if states is None else [criterion('state', states)]
        criteria += extra or []
        return dispatch(self.store, 'icp-propose', {'criteria': criteria,
            'exclusions': [], 'source_ids': [], 'strategic': True})

    def test_brazilian_state_codes_do_not_raise_country_divergence(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR'], ['SP', 'MG'])
        self.assertEqual(proposed.data['divergences'], [])
        self.assertEqual(proposed.data['status'], 'proposed')

    def test_country_and_long_state_names_match_codes_without_mutating_profile_or_predicates(self):
        for territory in (['São Paulo', 'Minas Gerais'], ['Brasil', 'São Paulo', 'Minas Gerais'],
                          ['BR', 'SP', 'MG'], [' brazil ', ' sao paulo ', 'MINAS GERAIS']):
            with self.subTest(territory=territory):
                configured = self.configure(territory)
                proposed = self.propose(['BR'], ['SP', 'MG'])
                self.assertEqual(proposed.data['divergences'], [])
                self.assertEqual(self.store.get('profile', 'current').data, configured.data)
                self.assertEqual(proposed.data['criteria'], [criterion('country', ['BR']), criterion('state', ['SP', 'MG'])])

    def test_country_scope_allows_its_known_states_without_comparing_state_to_country(self):
        self.configure(['Brasil'])
        proposed = self.propose(['BR'], ['São Paulo', 'MG'])
        self.assertEqual(proposed.data['divergences'], [])

    def test_real_country_and_state_divergences_remain_visible(self):
        self.configure(['SP', 'MG'])
        country = self.propose(['US'], ['SP'])
        self.assertEqual([d['field'] for d in country.data['divergences']], ['country'])
        state = self.propose(['BR'], ['RJ'])
        self.assertEqual([d['field'] for d in state.data['divergences']], ['state'])
        self.assertEqual(state.data['divergences'][0]['configured'], ['SP', 'MG'])
        self.assertEqual(state.data['divergences'][0]['proposed'], ['RJ'])

    def test_partial_overlap_cannot_silently_expand_geographic_scope(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR', 'US'], ['SP', 'RJ'])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['country', 'state'])

    def test_unknown_state_is_reviewed_even_when_it_overlaps_a_known_state(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR'], ['SP', 'Unknown district'])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['state'])

    def test_unknown_free_form_territory_does_not_establish_country_or_state(self):
        self.configure(['Unknown district'])
        proposed = self.propose(['BR'], ['Unknown district'])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['country', 'state'])

    def test_ambiguous_uf_country_code_requires_context_instead_of_assuming_brazil(self):
        self.configure(['MG'])
        ambiguous = self.propose(['BR'], ['MG'])
        self.assertTrue(ambiguous.data['divergences'])
        self.configure(['Brasil', 'MG'])
        contextual = self.propose(['BR'], ['MG'])
        self.assertEqual(contextual.data['divergences'], [])

    def test_other_legacy_country_remains_literal_without_inferring_foreign_states(self):
        self.configure(['US'])
        self.assertEqual(self.propose(['US']).data['divergences'], [])
        proposed = self.propose(['US'], ['SP'])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['state'])

    def test_territory_fix_preserves_industry_exclusions_and_reviewed_binding(self):
        self.configure(['São Paulo', 'Minas Gerais'], ['manufacturing'])
        proposed = self.propose(['BR'], ['SP', 'MG'], [criterion('industry', ['services'])])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['industry'])
        active = dispatch(self.store, 'icp-approve', {'id': proposed.id,
            'revision': proposed.revision, 'approved_by': 'seller-a'})
        self.store.put('campaign', 'c', {'status': 'active'}, None)
        bound = dispatch(self.store, 'icp-bind', {'campaign_id': 'c', 'icp_id': active.id, 'revision': active.revision})
        self.assertEqual(bound.data['icp_snapshot']['criteria'], proposed.data['criteria'])
        self.assertEqual(bound.data['icp_snapshot']['partner_exclusions'], ['Do not contact public agencies'])
        before = deepcopy(bound.data['icp_snapshot'])
        self.configure(['RJ'])
        self.assertEqual(self.store.get('campaign', 'c').data['icp_snapshot'], before)
        self.assertEqual(self.store.get('icp', active.id).data['approved_versions'][str(active.revision)], before)

    def test_geographic_change_still_requires_new_review_before_approval(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR'], ['SP', 'MG'])
        self.configure(['RJ'])
        with self.assertRaises(GateError) as caught:
            dispatch(self.store, 'icp-approve', {'id': proposed.id,
                'revision': proposed.revision, 'approved_by': 'seller-a'})
        self.assertEqual(caught.exception.code, 'icp_context_changed')

    def test_country_alone_cannot_hide_the_configured_state_recut(self):
        self.configure(['SP', 'MG'])
        broad = self.propose(['BR'])
        self.assertEqual([d['field'] for d in broad.data['divergences']], ['state'])
        contained = self.propose(['BR'], ['SP', 'MG'])
        self.assertEqual(contained.data['divergences'], [])

    def test_absent_geographic_predicates_still_expose_lost_state_restriction(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(extra=[criterion('industry', ['manufacturing'])])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['state'])

    def test_state_exclusion_does_not_replace_a_positive_state_recut(self):
        self.configure(['SP', 'MG'])
        excluded = dict(criterion('state', ['RJ']), operator='not_in')
        broad = self.propose(['BR'], extra=[excluded])
        self.assertEqual([d['field'] for d in broad.data['divergences']], ['state'])
        contained = self.propose(['BR'], ['SP', 'MG'], extra=[excluded])
        self.assertEqual(contained.data['divergences'], [])

    def test_conjoined_state_predicates_use_their_intersection_and_exclusions(self):
        self.configure(['SP', 'MG'])
        narrowed = self.propose(['BR'], ['SP', 'MG', 'RJ'], extra=[criterion('state', ['São Paulo', 'MG'])])
        self.assertEqual(narrowed.data['divergences'], [])
        excluded = self.propose(['BR'], ['SP', 'MG', 'RJ'],
            extra=[dict(criterion('state', ['RJ']), operator='not_in')])
        self.assertEqual(excluded.data['divergences'], [])

    def test_unsupported_ne_operator_is_still_rejected(self):
        self.configure(['SP', 'MG'])
        with self.assertRaises(GateError) as caught:
            self.propose(['BR'], extra=[dict(criterion('state', ['RJ']), operator='ne')])
        self.assertEqual(caught.exception.code, 'invalid_icp_predicate')

    def test_state_exclusions_are_part_of_the_same_geographic_recut(self):
        self.configure(['SP', 'MG'])
        broad = [criterion('country', ['BR']), criterion('state', ['SP', 'MG', 'RJ'])]
        narrowed = dispatch(self.store, 'icp-propose', {'criteria': broad,
            'exclusions': [criterion('state', ['RJ'])], 'source_ids': [], 'strategic': True})
        self.assertEqual(narrowed.data['divergences'], [])
        only_configured = dispatch(self.store, 'icp-propose', {'criteria': [criterion('country', ['BR'])],
            'exclusions': [dict(criterion('state', ['SP', 'MG']), operator='not_in')],
            'source_ids': [], 'strategic': True})
        self.assertEqual(only_configured.data['divergences'], [])

    def test_contradictory_state_recut_remains_explicit_for_review(self):
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR'], ['SP'],
            extra=[dict(criterion('state', ['SP']), operator='not_in')])
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['state'])


    def test_alias_exclusion_cannot_hide_a_code_that_the_runtime_gate_still_accepts(self):
        from aclad.accounts import icp_match
        self.configure(['SP', 'MG'])
        proposed = self.propose(['BR'], ['SP', 'MG', 'RJ'],
            extra=[dict(criterion('state', ['Rio de Janeiro']), operator='not_in')])
        self.assertEqual(icp_match({'country': 'BR', 'state': 'RJ'}, proposed.data), 'match')
        self.assertEqual([d['field'] for d in proposed.data['divergences']], ['state'])
