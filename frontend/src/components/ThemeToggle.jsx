import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon } from "lucide-react";
import { Button } from "./ui/button";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // next-themes reads localStorage on mount, which hasn't happened yet during
  // server/first-paint render — rendering the icon before that would briefly
  // show the wrong one. Bail out to a placeholder of the same size until mounted.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-9 w-9" />;
  }

  const isDark = theme === "dark";
  return (
    <Button
      variant="outline"
      size="icon"
      data-testid="theme-toggle"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
    </Button>
  );
}
