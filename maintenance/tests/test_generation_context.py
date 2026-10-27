from aclad.outcome_learning import propose_outcome_rule, review_outcome_rule, refresh_outcome_observations
from aclad.outreach import generation_context
from tests.test_outcome_observations import OutcomeFixture

class GenerationContextTests(OutcomeFixture):
    def test_email_uses_target_step_objective_approach_and_variant(self):
        self.send(with_context=True)
        observation=refresh_outcome_observations(self.store)[0]
        rule=propose_outcome_rule(self.store,{'task':'email','objective':'Meeting','approach':'Inventory','variant':'question'},
                                 'Ask a concise inventory question.',[observation.id])
        review_outcome_rule(self.store,rule.id,rule.revision,'approve','seller-review')
        context=generation_context(self.store,'campaign','a','contact-a',plan_step_id='step-a-1')
        self.assertEqual([row['id'] for row in context['outcome_rules']],[rule.id])
