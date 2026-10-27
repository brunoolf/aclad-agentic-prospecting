from dataclasses import replace

from aclad.models import GateError
from tests.results_support import seed_results
from tests.support import StateTest


class PrivacyTests(StateTest):
    def test_all_free_text_sentinels_are_absent(self):
        from aclad.result_metrics import calculate_results
        from aclad.results import render_results
        seed_results(self.store)
        sentinels = ['SENSITIVE_PARTNER', 'SENSITIVE_PERSON', 'secret@example.invalid',
            'https://sensitive.invalid', '11.222.333/0001-44', 'SENSITIVE_INDUSTRY',
            'SENSITIVE_TITLE', 'SENSITIVE_REVENUE', '/SENSITIVE/PATH', 'SENSITIVE_ERROR']
        for kind in ('campaign', 'account', 'contact', 'message', 'action', 'connection'):
            for row in self.store.list(kind):
                self.store.put(kind, row.id, dict(row.data, private_free_text=' '.join(sentinels)), row.revision)
        self.store.put('profile', 'current', {'name': ' '.join(sentinels)}, None)
        report = render_results(calculate_results(self.store))
        for sentinel in sentinels + ['campaign', 'partner-a', 'seller-a', 'instance-a', 'thread-0', 'apollo']:
            self.assertNotIn(sentinel, report)
        self.assertNotIn('http', report)
        self.assertNotIn('](', report)

    def test_renderer_has_closed_numeric_schema(self):
        from aclad.result_metrics import calculate_results, Rate
        from aclad.results import render_results
        metrics = calculate_results(self.store)
        report = render_results(metrics)
        self.assertEqual(report, """# Resultados

Projeção recalculada automaticamente a partir do estado confirmado. Edições deste arquivo não alteram o estado.

| Indicador | Quantidade |
|---|---:|
| Contas buscadas | 0 |
| Contas selecionadas pelo vendedor | 0 |
| Contas selecionadas atualmente | 0 |
| Contas contatadas | 0 |
| E-mails enviados | 0 |
| Respostas humanas recebidas | 0 |
| Contas com resposta humana | 0 |
| Reuniões marcadas | 0 |
| Reuniões ativas | 0 |
| Reuniões canceladas | 0 |
| Contas com reunião | 0 |
| Ações pendentes | 0 |

| Taxa | Numerador | Denominador | Percentual |
|---|---:|---:|---:|
| Seleção | 0 | 0 | N/D |
| Abordagem | 0 | 0 | N/D |
| Resposta | 0 | 0 | N/D |
| Agendamento | 0 | 0 | N/D |
| Resposta → reunião | 0 | 0 | N/D |

N/D indica denominador zero.

| Cobertura | Consultado | Total |
|---|---:|---:|
| Conversas acompanhadas | 0 | 0 |
| Contas no calendário | 0 | 0 |
| Fontes de contas | 0 | 0 |

Cobertura incompleta ou não consultada não comprova ausência de respostas ou reuniões.
""")
        self.assertEqual(report.count('N/D'), 6)  # Five rates plus fixed explanation.
        self.assertNotIn('ID', report)
        for invalid in (-1, True, 'private text'):
            with self.subTest(invalid=invalid), self.assertRaises((GateError, ValueError, TypeError)):
                render_results(replace(metrics, sent_messages=invalid))
        with self.assertRaises((GateError, ValueError, TypeError)):
            render_results({'name': 'private text'})
        with self.assertRaises((GateError, ValueError, TypeError)):
            Rate(2, 1)
