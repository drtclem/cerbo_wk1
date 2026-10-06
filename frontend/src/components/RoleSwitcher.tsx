import type { components } from "../api/schema.ts";

export type User = components["schemas"]["UserResponse"];

type RoleSwitcherProps = {
  users: User[];
  userId: number;
  onChange: (userId: number) => void;
};

export function RoleSwitcher({ users, userId, onChange }: RoleSwitcherProps) {
  return (
    <div className="role-switcher">
      <span className="role-switcher__label" id="role-switcher-label">
        Viewing as
      </span>
      <select
        aria-labelledby="role-switcher-label"
        value={userId}
        onChange={(event) => {
          onChange(Number(event.target.value));
        }}
      >
        {users.map((user) => (
          <option key={user.id} value={user.id}>
            {user.name} ({user.role})
          </option>
        ))}
      </select>
    </div>
  );
}
