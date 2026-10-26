import { createContext, useContext } from "react";
import type { User } from "./api";

export type SessionContextValue = {
  user: User | null;
  logout: () => Promise<void>;
  notify: (message: string, kind?: "success" | "error") => void;
};

export const SessionContext = createContext<SessionContextValue>({
  user: null,
  logout: async () => undefined,
  notify: () => undefined,
});

export const useSession = () => useContext(SessionContext);
