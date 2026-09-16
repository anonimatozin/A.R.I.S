"""
UI Skills - Design engineering guidelines for A.R.I.S.
Based on ibelick/ui-skills (MIT License).
Provides baseline-ui, accessibility, and motion performance rules.
"""

import json
from pathlib import Path
from typing import Dict, Optional

SKILLS_DIR = Path(__file__).parent.parent / "data" / "ui_skills"

SKILLS = {
    "baseline-ui": {
        "name": "Baseline UI",
        "description": "Fix spacing, hierarchy, typography, and layout issues. Fast cleanup/polish pass.",
        "rules": {
            "stack": [
                "MUST use Tailwind CSS defaults unless custom values exist or are explicitly requested",
                "MUST use motion/react (formerly framer-motion) when JavaScript animation is required",
                "SHOULD use tw-animate-css for entrance and micro-animations in Tailwind CSS",
                "MUST use cn utility (clsx + tailwind-merge) for class logic",
            ],
            "components": [
                "MUST use accessible component primitives for anything with keyboard/focus behavior (Base UI, React Aria, Radix)",
                "MUST use existing component primitives first",
                "NEVER mix primitive systems within the same interaction surface",
                "SHOULD prefer Base UI for new primitives if compatible with the stack",
                "MUST add aria-label to icon-only buttons",
                "NEVER rebuild keyboard or focus behavior by hand unless explicitly requested",
            ],
            "interaction": [
                "MUST use AlertDialog for destructive or irreversible actions",
                "SHOULD use structural skeletons for loading states",
                "NEVER use h-screen, use h-dvh",
                "MUST respect safe-area-inset for fixed elements",
                "MUST show errors next to where the action happens",
                "NEVER block paste in input or textarea elements",
            ],
            "animation": [
                "NEVER add animation unless it is explicitly requested",
                "MUST animate only compositor props (transform, opacity)",
                "NEVER animate layout properties (width, height, top, left, margin, padding)",
                "SHOULD avoid animating paint properties except for small, local UI",
                "SHOULD use ease-out on entrance",
                "NEVER exceed 200ms for interaction feedback",
                "MUST pause looping animations when off-screen",
                "SHOULD respect prefers-reduced-motion",
                "NEVER introduce custom easing curves unless explicitly requested",
                "SHOULD avoid animating large images or full-screen surfaces",
            ],
            "typography": [
                "MUST use text-balance for headings and text-pretty for body/paragraphs",
                "MUST use tabular-nums for data",
                "SHOULD use truncate or line-clamp for dense UI",
                "NEVER modify letter-spacing (tracking-*) unless explicitly requested",
            ],
            "layout": [
                "MUST use a fixed z-index scale (no arbitrary z-*)",
                "SHOULD use size-* for square elements instead of w-* + h-*",
            ],
            "performance": [
                "NEVER animate large blur() or backdrop-filter surfaces",
                "NEVER apply will-change outside an active animation",
                "NEVER use useEffect for anything that can be expressed as render logic",
            ],
            "design": [
                "NEVER use gradients unless explicitly requested",
                "NEVER use purple or multicolor gradients",
                "NEVER use glow effects as primary affordances",
                "SHOULD use Tailwind CSS default shadow scale unless explicitly requested",
                "MUST give empty states one clear next action",
                "SHOULD limit accent color usage to one per view",
                "SHOULD use existing theme or Tailwind CSS color tokens before introducing new ones",
            ],
        },
    },
    "fixing-accessibility": {
        "name": "Fixing Accessibility",
        "description": "Audit and fix HTML accessibility: ARIA labels, keyboard nav, focus management, contrast, forms.",
        "rules": {
            "accessible_names": [
                "Every interactive control must have an accessible name",
                "Icon-only buttons must have aria-label or aria-labelledby",
                "Every input, select, and textarea must be labeled",
                "Links must have meaningful text (no 'click here')",
                "Decorative icons must be aria-hidden",
            ],
            "keyboard_access": [
                "Do not use div or span as buttons without full keyboard support",
                "All interactive elements must be reachable by Tab",
                "Focus must be visible for keyboard users",
                "Do not use tabindex greater than 0",
                "Escape must close dialogs or overlays when applicable",
            ],
            "focus_and_dialogs": [
                "Modals must trap focus while open",
                "Restore focus to the trigger on close",
                "Set initial focus inside dialogs",
                "Opening a dialog should not scroll the page unexpectedly",
            ],
            "semantics": [
                "Prefer native elements (button, a, input) over role-based hacks",
                "If a role is used, required aria attributes must be present",
                "Lists must use ul or ol with li",
                "Do not skip heading levels",
                "Tables must use th for headers when applicable",
            ],
            "forms_and_errors": [
                "Errors must be linked to fields using aria-describedby",
                "Required fields must be announced",
                "Invalid fields must set aria-invalid",
                "Helper text must be associated with inputs",
                "Disabled submit actions must explain why",
            ],
            "announcements": [
                "Critical form errors should use aria-live",
                "Loading states should use aria-busy or status text",
                "Toasts must not be the only way to convey critical information",
                "Expandable controls must use aria-expanded and aria-controls",
            ],
            "contrast_and_states": [
                "Ensure sufficient contrast for text and icons",
                "Hover-only interactions must have keyboard equivalents",
                "Disabled states must not rely on color alone",
                "Do not remove focus outlines without a visible replacement",
            ],
        },
    },
    "fixing-motion-performance": {
        "name": "Fixing Motion Performance",
        "description": "Fix animation performance: layout thrashing, compositor properties, scroll-linked motion, blur.",
        "rules": {
            "never_patterns": [
                "Do not interleave layout reads and writes in the same frame",
                "Do not animate layout continuously on large or meaningful surfaces",
                "Do not drive animation from scrollTop, scrollY, or scroll events",
                "No requestAnimationFrame loops without a stop condition",
                "Do not mix multiple animation systems that each measure or mutate layout",
            ],
            "choose_mechanism": [
                "Default to transform and opacity for motion",
                "Use JS-driven animation only when interaction requires it",
                "Paint or layout animation is acceptable only on small, isolated surfaces",
                "One-shot effects are acceptable more often than continuous motion",
            ],
            "measurement": [
                "Measure once, then animate via transform or opacity",
                "Batch all DOM reads before writes",
                "Do not read layout repeatedly during an animation",
                "Prefer FLIP-style transitions for layout-like effects",
            ],
            "scroll": [
                "Prefer Scroll or View Timelines for scroll-linked motion when available",
                "Use IntersectionObserver for visibility and pausing",
                "Do not poll scroll position for animation",
                "Pause or stop animations when off-screen",
            ],
            "blur_and_filters": [
                "Keep blur animation small (<=8px)",
                "Use blur only for short, one-time effects",
                "Never animate blur continuously",
                "Never animate blur on large surfaces",
                "Prefer opacity and translate before blur",
            ],
        },
    },
}


class UISkills:
    """Manages UI design engineering skills for A.R.I.S."""

    def __init__(self):
        self.skills = SKILLS
        self._loaded = False

    def get_skill(self, skill_name: str) -> Optional[Dict]:
        """Get a specific skill by name."""
        return self.skills.get(skill_name)

    def get_all_skills(self) -> Dict[str, Dict]:
        """Get all available skills."""
        return self.skills

    def get_rules_for_context(self, context: str = "general") -> str:
        """Get relevant rules as a prompt string for the given context."""
        lines = ["## UI Design Rules (from ui-skills)"]

        if context in ("general", "ui", "dashboard", "frontend"):
            skill = self.skills.get("baseline-ui")
            if skill:
                lines.append(f"\n### {skill['name']}")
                for category, rules in skill["rules"].items():
                    lines.append(f"\n**{category.replace('_', ' ').title()}:**")
                    for rule in rules:
                        lines.append(f"- {rule}")

        if context in ("general", "ui", "accessibility", "a11y"):
            skill = self.skills.get("fixing-accessibility")
            if skill:
                lines.append(f"\n### {skill['name']}")
                for category, rules in skill["rules"].items():
                    lines.append(f"\n**{category.replace('_', ' ').title()}:**")
                    for rule in rules:
                        lines.append(f"- {rule}")

        if context in ("general", "animation", "motion", "performance"):
            skill = self.skills.get("fixing-motion-performance")
            if skill:
                lines.append(f"\n### {skill['name']}")
                for category, rules in skill["rules"].items():
                    lines.append(f"\n**{category.replace('_', ' ').title()}:**")
                    for rule in rules:
                        lines.append(f"- {rule}")

        return "\n".join(lines)

    def review_code(self, code: str, skill_name: str = "baseline-ui") -> str:
        """Review code against a specific skill's rules and return violations."""
        skill = self.skills.get(skill_name)
        if not skill:
            return f"Unknown skill: {skill_name}"

        violations = []
        code_lower = code.lower()

        if skill_name == "baseline-ui":
            checks = [
                ("h-screen", "NEVER use h-screen, use h-dvh"),
                ("will-change", "NEVER apply will-change outside an active animation"),
                ("letter-spacing", "NEVER modify letter-spacing unless explicitly requested"),
                ("gradient", "NEVER use gradients unless explicitly requested"),
                ("glow", "NEVER use glow effects as primary affordances"),
            ]
            for pattern, rule in checks:
                if pattern in code_lower:
                    violations.append(f"VIOLATION: {rule} (found '{pattern}' in code)")

        elif skill_name == "fixing-accessibility":
            checks = [
                ("<button>", "MUST add aria-label to icon-only buttons"),
                ("<div onclick", "Do not use div as button without full keyboard support"),
                ("<input", "Every input must be labeled"),
                ("tabindex=", "Do not use tabindex greater than 0"),
                ("role=", "If a role is used, required aria attributes must be present"),
            ]
            for pattern, rule in checks:
                if pattern in code_lower:
                    violations.append(f"VIOLATION: {rule} (found '{pattern}' in code)")

        elif skill_name == "fixing-motion-performance":
            checks = [
                ("transition: width", "MUST animate transform instead of width"),
                ("transition: height", "MUST animate transform instead of height"),
                ("transition: top", "MUST animate transform instead of top"),
                ("transition: left", "MUST animate transform instead of left"),
                ("scrollY", "Do not drive animation from scrollY"),
                ("requestAnimationFrame", "No rAF loops without a stop condition"),
            ]
            for pattern, rule in checks:
                if pattern in code_lower:
                    violations.append(f"VIOLATION: {rule} (found '{pattern}' in code)")

        if not violations:
            return f"No violations found against {skill['name']}."

        return f"Found {len(violations)} violation(s) against {skill['name']}:\n" + "\n".join(violations)

    def save_skills_to_disk(self):
        """Save skills data to disk for reference."""
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        for name, skill in self.skills.items():
            skill_file = SKILLS_DIR / f"{name}.json"
            with open(skill_file, "w", encoding="utf-8") as f:
                json.dump(skill, f, indent=2, ensure_ascii=False)

    def load_skills_from_disk(self) -> bool:
        """Load skills from disk if available."""
        if not SKILLS_DIR.exists():
            return False
        for skill_file in SKILLS_DIR.glob("*.json"):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    name = skill_file.stem
                    self.skills[name] = data
            except (json.JSONDecodeError, KeyError):
                continue
        self._loaded = True
        return True


_ui_skills_instance = None


def get_ui_skills() -> UISkills:
    """Get the singleton UI skills instance."""
    global _ui_skills_instance
    if _ui_skills_instance is None:
        _ui_skills_instance = UISkills()
        _ui_skills_instance.load_skills_from_disk()
    return _ui_skills_instance
