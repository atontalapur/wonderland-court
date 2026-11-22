import type { CharacterProfile } from "../theme/wonderland";

interface CharacterAvatarProps {
  character: CharacterProfile;
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
  align?: "left" | "center" | "right";
}

const SIZE_CLASSES = {
  sm: "h-11 w-11",
  md: "h-16 w-16 sm:h-[72px] sm:w-[72px]",
  lg: "h-20 w-20 sm:h-24 sm:w-24",
};

export function CharacterAvatar({
  character,
  size = "md",
  showLabel = true,
  align = "center",
}: CharacterAvatarProps) {
  const alignCls =
    align === "left"
      ? "items-start text-left"
      : align === "right"
        ? "items-end text-right"
        : "items-center text-center";

  return (
    <div className={`flex flex-col ${alignCls} shrink-0`}>
      <div className="relative">
        <div
          className={`${SIZE_CLASSES[size]} overflow-hidden rounded-full border-2 bg-[#fdf8ef] shadow-md ring-4 ${character.ringClass}`}
        >
          <img
            src={character.image}
            alt={character.name}
            className="h-full w-full object-cover"
            loading="eager"
          />
        </div>
        <span
          aria-hidden="true"
          className={`absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold shadow-sm ${character.badgeClass}`}
        >
          {character.suit}
        </span>
      </div>

      {showLabel && (
        <div className="mt-2">
          <div className="font-editorial text-sm font-bold leading-tight text-[#231f1a]">
            {character.name}
          </div>
          <div className="text-[11px] font-medium text-[#6b5e4e]">
            {character.role}
          </div>
        </div>
      )}
    </div>
  );
}
