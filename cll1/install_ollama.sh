#!/data/data/com.termux/files/usr/bin/bash
# install_ollama.sh — Instala Ollama + qwen2.5:1.5b no CLL1

echo "=== Instalando Ollama ==="
if command -v ollama &>/dev/null; then
    echo "Ollama ja instalado: $(ollama --version)"
else
    echo "Baixando Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo ""
echo "=== Iniciando Ollama ==="
if pgrep -f "ollama serve" >/dev/null; then
    echo "Ollama ja rodando"
else
    ollama serve &
    sleep 3
fi

echo ""
echo "=== Verificando RAM ==="
free -h

echo ""
echo "=== Instalando qwen2.5:1.5b ==="
ollama pull qwen2.5:1.5b

echo ""
echo "=== Modelos disponiveis ==="
ollama list

echo ""
echo "=== Teste rapido ==="
ollama run qwen2.5:1.5b "Ola, voce esta funcionando?" --nowordwrap

echo ""
echo "=== Pronto! ==="
