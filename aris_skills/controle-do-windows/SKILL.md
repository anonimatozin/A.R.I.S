---
name: controle-do-windows
description: Controlar o Windows no ciclo observar → agir → verificar — identificar janela e controles por UI Automation antes de usar coordenadas de mouse/teclado e nunca assumir que um clique funcionou sem checar. Use quando for abrir programas, clicar, digitar ou navegar na interface do Windows.
---

## Objetivo

Operar a interface do Windows de forma confiável: cada ação é confirmada por uma
nova observação do estado, não pela suposição de que deu certo.

## Quando usar

- Abrir programas, preencher formulários, clicar em botões, navegar menus.
- Automatizar tarefa gráfica (sem API/linha de comando disponível).
- Verificar se uma janela abriu, se um diálogo apareceu, se o valor mudou.

## O ciclo (sempre nesta ordem)

1. **Observar** — liste as janelas abertas e o que está visível. Prefira leitura por
   UI Automation (título, controles, papéis, valores) a adivinhar por coordenadas.
2. **Agir** — uma ação por vez: clicar no controle identificado, digitar texto,
   pressionar tecla. Coordenadas só quando não houver controle acessível.
3. **Verificar** — observe de novo: o diálogo apareceu? o texto entrou? a janela
   mudou de título? Se não mudou, **não repita às cegas**: investigue (janela em
   segundo plano? controle desabilitado? popup diferente?).
4. Repita até a tarefa terminar ou dar 3 tentativas sem progresso → pare e relate.

## Regras

- Nunca assuma que um clique funcionou: sempre há uma verificação depois.
- Janela correta primeiro: confirme título/PID antes de digitar (não digite na
  janela errada).
- Espere a UI assentar (0,3–1 s) antes de observar; diálogos demoram para abrir.
- Sempre que houver caminho por teclado/menu acessível, prefira a coordenada pixel.
- Desconfie de janelas modais (bloqueiam o resto): feche ou responda antes de seguir.
- Capture o estado em caso de falha: títulos das janelas e o que estava visível.
- Ferramentas destrutivas na UI (formatar disco, excluir, desinstalar) pedem
  confirmação do usuário antes do clique final.
- Anote em log cada ação observada → agida → verificada (uma linha por ciclo).

## Exemplo de registro

```
[observar] janela "Sem título — Bloco de Notas", controle Edit vazio
[agir]     digitar "oi" no Edit
[verificar] Edit = "oi"  → ok
```

## Quando parar

- 3 ciclos sem mudança observável.
- Janela/sistema travado, ou ação pede permissão de administrador.
- A tarefa saiu do que o usuário pediu.
