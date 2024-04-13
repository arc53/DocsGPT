import React from 'react';
import Dropdown from '../components/Dropdown';

const Widgets: React.FC<{
  widgetScreenshot: File | null;
  onWidgetScreenshotChange: (screenshot: File | null) => void;
}> = ({ widgetScreenshot, onWidgetScreenshotChange }) => {
  const widgetSources = ['Source 1', 'Source 2', 'Source 3'];
  const widgetMethods = ['Method 1', 'Method 2', 'Method 3'];
  const widgetTypes = ['Type 1', 'Type 2', 'Type 3'];

  const [selectedWidgetSource, setSelectedWidgetSource] = React.useState(
    widgetSources[0],
  );
  const [selectedWidgetMethod, setSelectedWidgetMethod] = React.useState(
    widgetMethods[0],
  );
  const [selectedWidgetType, setSelectedWidgetType] = React.useState(
    widgetTypes[0],
  );

  // const [widgetScreenshot, setWidgetScreenshot] = useState<File | null>(null);
  const [widgetCode, setWidgetCode] = React.useState<string>(''); // Your widget code state

  const handleScreenshotChange = (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = event.target.files;

    if (files && files.length > 0) {
      const selectedScreenshot = files[0];
      onWidgetScreenshotChange(selectedScreenshot); // Update the screenshot in the parent component
    }
  };

  const handleCopyToClipboard = () => {
    // Create a new textarea element to select the text
    const textArea = document.createElement('textarea');
    textArea.value = widgetCode;
    document.body.appendChild(textArea);

    // Select and copy the text
    textArea.select();
    document.execCommand('copy');

    // Clean up the textarea element
    document.body.removeChild(textArea);
  };

  return (
    <div>
      <div className="mt-[59px]">
        <p className="font-bold text-jet">Widget Source</p>
        <Dropdown
          options={widgetSources}
          selectedValue={selectedWidgetSource}
          onSelect={setSelectedWidgetSource}
        />
      </div>
      <div className="mt-5">
        <p className="font-bold text-jet">Widget Method</p>
        <Dropdown
          options={widgetMethods}
          selectedValue={selectedWidgetMethod}
          onSelect={setSelectedWidgetMethod}
        />
      </div>
      <div className="mt-5">
        <p className="font-bold text-jet">Widget Type</p>
        <Dropdown
          options={widgetTypes}
          selectedValue={selectedWidgetType}
          onSelect={setSelectedWidgetType}
        />
      </div>
      <div className="mt-6">
        <p className="font-bold text-jet">Widget Code Snippet</p>
        <textarea
          rows={4}
          value={widgetCode}
          onChange={(e) => setWidgetCode(e.target.value)}
          className="mt-3 w-full rounded-lg border-2 p-2"
        />
      </div>
      <div className="mt-1">
        <button
          onClick={handleCopyToClipboard}
          className="rounded-lg bg-blue-400 px-2 py-2 font-bold text-white transition-all hover:bg-blue-600"
        >
          Copy
        </button>
      </div>

      <div className="mt-4">
        <p className="text-lg font-semibold">Widget Screenshot</p>
        <input type="file" accept="image/*" onChange={handleScreenshotChange} />
      </div>

      {widgetScreenshot && (
        <div className="mt-4">
          <img
            src={URL.createObjectURL(widgetScreenshot)}
            alt="Widget Screenshot"
            className="max-w-full rounded-lg border border-gray-300"
          />
        </div>
      )}
    </div>
  );
};

export default Widgets;
