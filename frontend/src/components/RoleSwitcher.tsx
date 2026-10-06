import type { components } from "../api/schema.ts";

export type User = components["schemas"]["UserResponse"];

type RoleSwitcherProps = {
  users: User[];
  userId: number;
  onChange: (userId: number) => void;
};

export function RoleSwitcher({ users, userId, onChange }: RoleSwitcherProps) {
  return (
    <label>
      Role
      <select
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
    </label>
  );
}
