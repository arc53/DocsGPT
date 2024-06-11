import { DocumentsProps } from '../models/misc';
import Trash from '../assets/trash.svg';
import PropTypes from 'prop-types';
import { useTranslation } from 'react-i18next';

// Utility function to format numbers
const formatTokens = (tokens: number): string => {
  const roundToTwoDecimals = (num: number): string => {
    return (Math.round((num + Number.EPSILON) * 100) / 100).toString();
  };

  if (tokens >= 1_000_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000_000) + 'b';
  } else if (tokens >= 1_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000) + 'm';
  } else if (tokens >= 1_000) {
    return roundToTwoDecimals(tokens / 1_000) + 'k';
  } else {
    return tokens.toString();
  }
};

const Documents: React.FC<DocumentsProps> = ({
  documents,
  handleDeleteDocument,
}) => {
  const { t } = useTranslation();
  return (
    <div className="mt-8">
      <div className="flex flex-col">
        <div className="w-full overflow-x-auto">
          <table className="block w-max table-auto content-center justify-center rounded-xl border text-center dark:border-chinese-silver dark:text-bright-gray">
            <thead>
              <tr>
                <th className="border-r p-4 md:w-[244px]">
                  {t('settings.documents.name')}
                </th>
                <th className="w-[244px] border-r px-4 py-2">
                  {t('settings.documents.date')}
                </th>
                <th className="w-[244px] border-r px-4 py-2">
                  {t('settings.documents.tokenUsage')}
                </th>
                <th className="w-[244px] border-r px-4 py-2">
                  {t('settings.documents.type')}
                </th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {documents &&
                documents.map((document, index) => (
                  <tr key={index}>
                    <td className="border-r border-t px-4 py-2">
                      {document.name}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.date}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.tokens ? formatTokens(+document.tokens) : ''}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.location === 'remote'
                        ? 'Pre-loaded'
                        : 'Private'}
                    </td>
                    <td className="border-t px-4 py-2">
                      {document.location !== 'remote' && (
                        <img
                          src={Trash}
                          alt="Delete"
                          className="h-4 w-4 cursor-pointer hover:opacity-50"
                          id={`img-${index}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleDeleteDocument(index, document);
                          }}
                        />
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
Documents.propTypes = {
  documents: PropTypes.array.isRequired,
  handleDeleteDocument: PropTypes.func.isRequired,
};
export default Documents;
