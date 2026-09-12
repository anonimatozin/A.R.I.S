"""Turbo Mode - Análise Profunda do A.R.I.S.

Modo de análise aprofundada de arquivos, código e imagens.
"""

import os
import json
from pathlib import Path
from typing import Optional
from utils.logger import Logger


class TurboMode:
    """Modo Turbo para análises profundas."""

    def __init__(self, logger: Optional[Logger] = None):
        self._logger = logger
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def activate(self) -> str:
        """Ativa o modo turbo."""
        self._active = True
        return "⚡ Modo Turbo ATIVADO — Análise profunda habilitada"

    def deactivate(self) -> str:
        """Desativa o modo turbo."""
        self._active = False
        return "Modo Turbo desativado"

    def analyze_file(self, filepath: str) -> str:
        """Analisa um arquivo em profundidade.

        Args:
            filepath: Caminho do arquivo.

        Returns:
            Análise detalhada do arquivo.
        """
        path = Path(filepath)
        if not path.exists():
            return f"Arquivo não encontrado: {filepath}"

        try:
            stat = path.stat()
            size_kb = stat.st_size / 1024

            # Informações básicas
            info = [
                f"📄 **Análise: {path.name}**",
                f"   Caminho: {path.absolute()}",
                f"   Tamanho: {size_kb:.1f} KB",
                f"   Modificado: {stat.st_mtime:.0f}",
            ]

            # Ler conteúdo se for texto
            if path.suffix.lower() in (".py", ".js", ".ts", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".env", ".html", ".css"):
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.split("\n")
                    info.append(f"   Linhas: {len(lines)}")

                    # Análise básica de código
                    if path.suffix.lower() == ".py":
                        info.extend(self._analyze_python(lines))
                    elif path.suffix.lower() in (".js", ".ts"):
                        info.extend(self._analyze_javascript(lines))

                    # Estatísticas gerais
                    info.append(f"   Caracteres: {len(content)}")
                    info.append(f"   Palavras: {len(content.split())}")

                except Exception as e:
                    info.append(f"   Erro ao ler: {e}")
            else:
                info.append(f"   Tipo: {path.suffix} (não analisável como texto)")

            return "\n".join(info)

        except Exception as e:
            return f"Erro ao analisar arquivo: {e}"

    def _analyze_python(self, lines: list[str]) -> list[str]:
        """Análise específica de código Python."""
        analysis = []
        classes = []
        functions = []
        imports = []
        globals_count = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("class "):
                name = stripped.split("(")[0].replace("class ", "").strip()
                classes.append(f"L{i}: {name}")
            elif stripped.startswith("def "):
                name = stripped.split("(")[0].replace("def ", "").strip()
                functions.append(f"L{i}: {name}")
            elif stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped[:60])
            elif stripped.startswith("global "):
                globals_count += 1

        if classes:
            analysis.append(f"   Classes ({len(classes)}): {', '.join(c.split(': ')[1] for c in classes[:5])}")
        if functions:
            analysis.append(f"   Funções ({len(functions)}): {', '.join(f.split(': ')[1] for f in functions[:8])}")
        if imports:
            analysis.append(f"   Imports ({len(imports)}): {imports[0][:50]}{'...' if len(imports) > 1 else ''}")

        return analysis

    def _analyze_javascript(self, lines: list[str]) -> list[str]:
        """Análise específica de código JavaScript/TypeScript."""
        analysis = []
        functions = []
        imports = []
        exports = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "function " in stripped or "=>" in stripped:
                functions.append(f"L{i}")
            elif stripped.startswith("import ") or stripped.startswith("const {"):
                imports.append(stripped[:60])
            elif "export " in stripped:
                exports += 1

        if functions:
            analysis.append(f"   Funções: {len(functions)}")
        if imports:
            analysis.append(f"   Imports: {len(imports)}")
        if exports:
            analysis.append(f"   Exports: {exports}")

        return analysis

    def analyze_directory(self, dirpath: str, max_depth: int = 2) -> str:
        """Analisa um diretório em profundidade.

        Args:
            dirpath: Caminho do diretório.
            max_depth: Profundidade máxima.

        Returns:
            Análise do diretório.
        """
        path = Path(dirpath)
        if not path.exists() or not path.is_dir():
            return f"Diretório não encontrado: {dirpath}"

        info = [f"📁 **Análise: {path.name}**"]

        stats = {
            "total_files": 0,
            "total_dirs": 0,
            "total_size": 0,
            "extensions": {},
            "largest_files": [],
        }

        self._scan_directory(path, stats, 0, max_depth)

        info.append(f"   Arquivos: {stats['total_files']}")
        info.append(f"   Diretórios: {stats['total_dirs']}")
        info.append(f"   Tamanho total: {stats['total_size'] / 1024:.1f} KB")

        # Top extensões
        exts = sorted(stats["extensions"].items(), key=lambda x: x[1], reverse=True)[:5]
        if exts:
            ext_str = ", ".join(f"{e}: {c}" for e, c in exts)
            info.append(f"   Extensões: {ext_str}")

        # Maiores arquivos
        stats["largest_files"].sort(key=lambda x: x[1], reverse=True)
        if stats["largest_files"]:
            info.append("   Maiores arquivos:")
            for name, size in stats["largest_files"][:5]:
                info.append(f"     - {name}: {size / 1024:.1f} KB")

        return "\n".join(info)

    def _scan_directory(self, path: Path, stats: dict, depth: int, max_depth: int) -> None:
        """Escaneia recursivamente um diretório."""
        if depth > max_depth:
            return

        try:
            for item in path.iterdir():
                if item.name.startswith(".") or item.name in ("__pycache__", "node_modules", ".git", "venv", ".venv"):
                    continue

                if item.is_dir():
                    stats["total_dirs"] += 1
                    self._scan_directory(item, stats, depth + 1, max_depth)
                elif item.is_file():
                    stats["total_files"] += 1
                    size = item.stat().st_size
                    stats["total_size"] += size

                    ext = item.suffix.lower()
                    stats["extensions"][ext] = stats["extensions"].get(ext, 0) + 1

                    stats["largest_files"].append((item.name, size))
                    if len(stats["largest_files"]) > 10:
                        stats["largest_files"].sort(key=lambda x: x[1], reverse=True)
                        stats["largest_files"] = stats["largest_files"][:10]
        except PermissionError:
            pass

    def code_review(self, filepath: str) -> str:
        """Faz um code review básico.

        Args:
            filepath: Caminho do arquivo.

        Returns:
            Review do código.
        """
        path = Path(filepath)
        if not path.exists():
            return f"Arquivo não encontrado: {filepath}"

        if path.suffix.lower() != ".py":
            return "Code review disponível apenas para Python (.py)"

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")
            issues = []

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Linhas muito longas
                if len(line) > 120:
                    issues.append(f"L{i}: ⚠️ Linha muito longa ({len(line)} chars)")

                # TODO/FIXME
                if "TODO" in stripped or "FIXME" in stripped:
                    issues.append(f"L{i}: 📝 TODO/FIXME encontrado")

                # Print statements
                if stripped.startswith("print(") and "debug" not in stripped.lower():
                    issues.append(f"L{i}: 🐛 Print statement (use logging)")

                # Bare except
                if stripped == "except:":
                    issues.append(f"L{i}: ⚠️ Bare except (especifique a exceção)")

                # Global variables
                if stripped.startswith("global "):
                    issues.append(f"L{i}: ⚠️ Uso de global")

            if not issues:
                return f"✅ Code Review: Nenhum problema encontrado em {path.name}"

            report = [f"📋 **Code Review: {path.name}** ({len(issues)} issues)"]
            report.extend(issues[:20])
            if len(issues) > 20:
                report.append(f"... e mais {len(issues) - 20} issues")
            return "\n".join(report)

        except Exception as e:
            return f"Erro ao analisar: {e}"

    def get_file_diff_summary(self, file1: str, file2: str) -> str:
        """Compara dois arquivos e resume diferenças."""
        try:
            with open(file1, "r", encoding="utf-8", errors="ignore") as f:
                lines1 = set(f.readlines())
            with open(file2, "r", encoding="utf-8", errors="ignore") as f:
                lines2 = set(f.readlines())

            added = lines2 - lines1
            removed = lines1 - lines2

            report = [
                f"📊 **Diff: {Path(file1).name} vs {Path(file2).name}**",
                f"   Linhas adicionadas: {len(added)}",
                f"   Linhas removidas: {len(removed)}",
            ]

            return "\n".join(report)
        except Exception as e:
            return f"Erro ao comparar: {e}"
