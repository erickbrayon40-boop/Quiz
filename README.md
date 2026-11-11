# Quiz do 2º Ano

Quiz sobre advérbios com 15 perguntas, pontuação validada no servidor, revisão e ranking compartilhado. As tentativas são salvas em `data/attempts.json` no servidor. O navegador guarda apenas o token de retomada e as preferências.

## Iniciar no Windows

Dê dois cliques em `INICIAR.bat`. O script instala as dependências se necessário e inicia o servidor. Abra http://localhost:5000. Mantenha a janela do servidor aberta enquanto a turma estiver jogando. O aplicativo usa o servidor Waitress; se a porta 5000 já estiver ocupada, feche o servidor anterior antes de iniciar outro.

Para acesso na mesma rede, os demais dispositivos podem usar o endereço de rede exibido ao iniciar o servidor, desde que o firewall permita o acesso. O computador que executa o servidor precisa ficar ligado; todos os participantes devem usar o mesmo servidor para compartilhar o ranking.

Para instalar e iniciar manualmente:

```powershell
python -m pip install -r requirements.txt
python app.py
```

## Jogar em grupo

1. O líder informa o nome e escolhe **Criar grupo**. Ele recebe um código numérico de oito dígitos.
2. Cada aluno abre o mesmo site, informa seu nome e digita o código em **Entrar no grupo**. A lista lateral mostra o líder e os alunos.
3. Quando quiser, o líder clica em **Iniciar quiz**; ele também pode iniciar sozinho. Todos que entraram antes do início respondem individualmente.

Os participantes precisam conseguir acessar o mesmo servidor. Em uma rede local, use o endereço de rede exibido pelo servidor, e não `localhost` no celular. O código da sala não publica o site na internet. As salas são gravadas no mesmo JSON e podem ser retomadas no mesmo navegador enquanto os dados dele não forem apagados.

## Publicar para acesso pela internet

O projeto precisa de uma hospedagem Python com **disco persistente compartilhado**: sistemas que apagam arquivos a cada reinício, publicam apenas arquivos estáticos ou distribuem cópias independentes não servem para este banco. Configure `QUIZ_DATA_FILE` com um caminho no disco persistente, por exemplo `/data/attempts.json`, e inicie com `gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app`. O diretório precisa permitir leitura e escrita pelo processo. Uma única instância mantém o arquivo e seu bloqueio no mesmo disco; faça backup periódico do arquivo. O arquivo JSON nunca deve ser publicado como conteúdo estático.

A aplicação não tem link público enquanto não for instalada em uma hospedagem. Em Windows, use o servidor local fornecido para a apresentação ou uma hospedagem compatível para acesso externo.

## Funcionamento e privacidade

Cada tentativa recebe um token aleatório e o servidor guarda somente o hash. O nome não identifica uma pessoa de forma única. O bloqueio de arquivo e a gravação atômica protegem respostas simultâneas; o servidor valida a ordem e calcula os acertos. Somente tentativas concluídas aparecem no ranking, ordenadas por acertos, tempo e data. Uma tentativa pode ser retomada no mesmo navegador; limpar seus dados remove o token de acesso.

Nenhum sistema sem contas pode impedir que a mesma pessoa faça várias tentativas ou que compartilhe suas respostas. O arquivo de dados deve ser acessível somente ao servidor e a quem administra a hospedagem.

## Testes

Execute `python -m unittest discover -s tests -v`. Os testes usam diretórios temporários e não alteram o ranking real.

## Nomes e proteção contra spam

Para criar ou entrar em uma sala, informe nome e sobrenome com até 30 caracteres. O formato aceita acentos, hífens e apóstrofos, mas não comprova a identidade do jogador. O servidor limita temporariamente pedidos repetidos de criação de salas e entradas por endereço de rede; isso não impõe um limite de participantes por sala. Os limites são guardados na memória do processo e recomeçam quando ele reinicia.
