# Manutenção

O plugin distribuído fica em `plugins/aclad-prospecting`. Os catálogos na raiz apontam para essa pasta.

Executar os testes locais:

```sh
PYTHONPATH=plugins/aclad-prospecting/runtime:maintenance python3 -m unittest discover -s maintenance/tests -q
```

Gerar um pacote fora do repositório:

```sh
python3 maintenance/tools/build_plugin.py --destination /tmp/aclad-packages --surface codex
python3 maintenance/tools/build_plugin.py --destination /tmp/aclad-packages --surface claude
```

Não incluir dados de vendedores, credenciais, contextos privados ou materiais internos nos pacotes.
