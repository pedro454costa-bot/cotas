# Instalação — Risk Map

Requisito único: **Python 3.10 ou superior**. Confira com `python --version`.

Não é preciso Node.js, npm nem internet para o frontend — a única biblioteca
JavaScript (vis-network) já está dentro do projeto, em `frontend_web/vendor/`.

---

## Caminho A — a máquina tem acesso ao PyPI

```bash
cd "Sistema de Cotas - Simples"
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python executar.py
```

São **duas** bibliotecas: `fastapi` e `uvicorn`. O restante (`sqlite3`, `json`,
`pathlib`) vem na biblioteca padrão do Python.

---

## Caminho B — rede corporativa com proxy

```bash
pip install -r requirements.txt --proxy http://usuario:senha@proxy.empresa:8080
```

Se a empresa tem repositório interno (Nexus, Artifactory):

```bash
pip install -r requirements.txt --index-url https://repo.empresa/pypi/simple --trusted-host repo.empresa
```

---

## Caminho C — máquina sem internet (instalação offline)

A pasta `offline/` já contém todos os pacotes necessários, baixados como wheels.
Leve o projeto inteiro (incluindo essa pasta) e instale sem rede:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install --no-index --find-links offline -r requirements.txt
python executar.py
```

**Atenção:** os wheels em `offline/` foram baixados para **Windows 64 bits com
Python 3.12**. O pacote `pydantic_core` é compilado, não é código puro — em outra
combinação de sistema ou versão de Python ele não serve. Nesse caso, regere a
pasta numa máquina com internet e o mesmo Python de destino:

```bash
pip download -r requirements.txt -d offline
```

---

## Rodando

```bash
python executar.py
```

Sobe em <http://127.0.0.1:8000> e abre o navegador. `Ctrl+C` encerra.

A documentação automática da API fica em <http://127.0.0.1:8000/docs>.

---

## Pipelines (opcional)

Só é necessário para **atualizar** os dados. Para apenas abrir a tela com o que
já está no banco, ignore esta seção.

```bash
pip install -r requirements.txt -r requirements-pipeline.txt
```

Acrescenta `pandas`, `requests`, `pypdf`, `openpyxl` e `openai`.

A análise por IA precisa de uma chave da OpenAI num arquivo `.env` na raiz:

```
OPENAI_API_KEY=sk-proj-...
```

O `.env` está no `.gitignore` — a chave nunca deve ser versionada.

---

## O que levar para a outra máquina

| Pasta / arquivo | Obrigatório | Observação |
|---|---|---|
| `backend/` | sim | API |
| `frontend_web/` | sim | interface, inclui `vendor/vis-network.min.js` |
| `db/cotas.db` | sim | o banco com os dados (~cheque o tamanho) |
| `config.py`, `executar.py` | sim | |
| `requirements*.txt` | sim | |
| `offline/` | só no caminho C | 3,2 MB |
| `pipeline/` | só se for atualizar dados | |
| `exports/` | não | planilhas de trabalho, regeneráveis |
| `.venv/` | **não** | recriar na máquina de destino |
| `.env` | **não** | a chave é pessoal, criar no destino |

---

## Problemas comuns

**`ModuleNotFoundError: No module named 'fastapi'`**
O ambiente virtual não está ativo. Rode `.venv\Scripts\activate` antes.

**`[Errno 10048] address already in use`**
A porta 8000 está ocupada. Altere `PORTA` em `executar.py`.

**A tela abre mas o grafo não desenha**
Confira no console do navegador (F12) se aparece `Risk Map · frontend vN`. Se o
`vendor/vis-network.min.js` não tiver ~676 KB, o arquivo veio incompleto.

**`unable to open database file`**
`db/cotas.db` não foi copiado, ou a pasta está somente-leitura. A API lê o banco
em modo read-only, mas precisa de permissão de escrita para a tabela
`lista_negativa`, criada na primeira execução.
