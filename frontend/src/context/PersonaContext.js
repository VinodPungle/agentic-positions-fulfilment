import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

const PersonaContext = createContext(null);

export function PersonaProvider({ children }) {
  const [users, setUsers] = useState([]);
  const [user, setUser] = useState(null);

  useEffect(() => {
    api.get("/users").then((res) => {
      setUsers(res.data);
      // Persona resolution order: whatever was last selected (localStorage) -> the
      // Service Line Leader (broadest account-wide view, a sensible default) ->
      // whoever's first. There's no real auth here — X-User-Id (set in api.js from
      // this same localStorage value) is how the backend knows "who" is calling.
      const saved = localStorage.getItem("personaId");
      const found = res.data.find((u) => u.id === saved) || res.data.find((u) => u.role === "service_line_leader") || res.data[0];
      if (found) {
        localStorage.setItem("personaId", found.id);
        setUser(found);
      }
    }).catch(() => {
      // Already logged by the axios response interceptor in lib/api.js; swallowed
      // here only to avoid an unhandled promise rejection warning.
    });
  }, []);

  const setPersona = (id) => {
    const found = users.find((u) => u.id === id);
    if (found) {
      localStorage.setItem("personaId", id);
      setUser(found);
    }
  };

  return <PersonaContext.Provider value={{ users, user, setPersona }}>{children}</PersonaContext.Provider>;
}

export const usePersona = () => useContext(PersonaContext);
