import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../lib/api";

const PersonaContext = createContext(null);

export function PersonaProvider({ children }) {
  const [users, setUsers] = useState([]);
  const [user, setUser] = useState(null);

  useEffect(() => {
    api.get("/users").then((res) => {
      setUsers(res.data);
      const saved = localStorage.getItem("personaId");
      const found = res.data.find((u) => u.id === saved) || res.data.find((u) => u.role === "dm") || res.data[0];
      if (found) {
        localStorage.setItem("personaId", found.id);
        setUser(found);
      }
    }).catch(() => {});
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
