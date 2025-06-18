import Robot from '../assets/robot.svg';
import { Agent } from './types';

export default function SharedAgentCard({ agent }: { agent: Agent }) {
  return (
    <div className="flex w-full max-w-[720px] flex-col rounded-3xl border border-dark-gray p-6 shadow-sm dark:border-grey sm:w-fit sm:min-w-[480px]">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-full p-1">
          <img
            src={agent.image && agent.image.trim() !== '' ? agent.image : Robot}
            className="h-full w-full rounded-full object-contain"
          />
        </div>
        <div className="flex max-h-[92px] w-[80%] flex-col gap-px">
          <h2 className="text-base font-semibold text-[#212121] dark:text-[#E0E0E0] sm:text-lg">
            {agent.name}
          </h2>
          <p className="overflow-y-auto text-wrap break-all text-xs text-[#71717A] dark:text-[#949494] sm:text-sm">
            {agent.description}
          </p>
        </div>
      </div>
      {agent.shared_metadata && (
        <div className="mt-4 flex items-center gap-8">
          {agent.shared_metadata?.shared_by && (
            <p className="text-xs font-light text-[#212121] dark:text-[#E0E0E0] sm:text-sm">
              by {agent.shared_metadata.shared_by}
            </p>
          )}
          {agent.shared_metadata?.shared_at && (
            <p className="text-xs font-light text-[#71717A] dark:text-[#949494] sm:text-sm">
              Shared on{' '}
              {new Date(agent.shared_metadata.shared_at).toLocaleString(
                'en-US',
                {
                  month: 'long',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: true,
                },
              )}
            </p>
          )}
        </div>
      )}
      {agent.tool_details && agent.tool_details.length > 0 && (
        <div className="mt-8">
          <p className="text-sm font-semibold text-[#212121] dark:text-[#E0E0E0] sm:text-base">
            Connected Tools
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {agent.tool_details.map((tool, index) => (
              <span
                key={index}
                className="flex items-center gap-1 rounded-full bg-bright-gray px-3 py-1 text-xs font-light text-[#212121] dark:bg-dark-charcoal dark:text-[#E0E0E0]"
              >
                <img
                  src={`/toolIcons/tool_${tool.name}.svg`}
                  alt={`${tool.name} icon`}
                  className="h-3 w-3"
                />{' '}
                {tool.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
