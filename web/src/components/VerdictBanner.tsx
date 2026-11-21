import { CHARACTERS } from "../theme/wonderland";
import type { Verdict } from "../types/events";
import { CharacterAvatar } from "./CharacterAvatar";

interface VerdictBannerProps {
  verdict: Verdict;
}

export function VerdictBanner({ verdict }: VerdictBannerProps) {
  const isLeak = verdict.ruling === "leak";

  return (
    <div
      className={`mt-5 flex flex-col gap-3 rounded-2xl border-2 p-4 sm:flex-row sm:items-center ${
        isLeak
          ? "border-[#e58b99] bg-[#fff4f6]"
          : "border-[#9ad8be] bg-[#f2fbf7]"
      }`}
      data-testid="verdict-banner"
    >
      <CharacterAvatar
        character={CHARACTERS.queen}
        size="sm"
        showLabel={false}
      />

      <div className="flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="font-editorial text-xs font-bold uppercase tracking-wider text-[#6b5e4e]">
            Queen of Hearts rules:
          </span>
          <span
            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-0.5 font-editorial text-xs font-bold tracking-wide ${
              isLeak
                ? "court-stamp-leak bg-[#ffe2e7] text-[#a5152e]"
                : "court-stamp-held bg-[#dcfce7] text-[#065f46]"
            }`}
          >
            {isLeak ? "♥ OFF WITH HER HEAD!" : "♣ ALICE HELD FIRM!"}
          </span>
        </div>

        <p className="mt-1.5 text-sm leading-relaxed text-[#3a3026]">
          “{verdict.reason}”
        </p>
      </div>
    </div>
  );
}
