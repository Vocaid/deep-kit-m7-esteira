"""Com `python -I`, sinais/ nao entra no sys.path: inserimos o diretorio explicitamente.
Convencao para todas as tarefas: `import metricas` (e `import registrador`...) apos este insert."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
