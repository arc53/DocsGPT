import { vscDarkPlus } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import remarkGfm from 'remark-gfm';
import ReactMarkdown from 'react-markdown'
import classes from './Response.module.css'
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/light-async';
interface typeProps {
    message:string
}
const Response = (props:typeProps) => {
    return (
        <ReactMarkdown
            className="whitespace-pre-wrap break-words max-w-72"
            remarkPlugins={[remarkGfm]}
            components={{
                code({ node, className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || '');

                    return match ? (
                        <SyntaxHighlighter
                            PreTag="div"
                            wrapLines={true}
                            lineProps={{style: {width:'',overflowX:'scroll'}}}
                            language={match[1]}
                            style={vscDarkPlus}
                        >
                            {String(children).replace(/\n$/, '')}
                        </SyntaxHighlighter>
                    ) : (
                        <code className={className ? className : ''} {...props}>
                            {children}
                        </code>
                    );
                },
                ul({ children }) {
                    return (
                        <ul
                            className={`list-inside list-disc whitespace-normal pl-4 ${classes.list}`}
                        >
                            {children}
                        </ul>
                    );
                },
                ol({ children }) {
                    return (
                        <ol
                            className={`list-inside list-decimal whitespace-normal pl-4 ${classes.list}`}
                        >
                            {children}
                        </ol>
                    );
                },
                table({ children }) {
                    return (
                        <div className="relative overflow-x-auto rounded-lg border">
                            <table className="w-full text-left text-sm text-gray-700">
                                {children}
                            </table>
                        </div>
                    );
                },
                thead({ children }) {
                    return (
                        <thead className="text-xs uppercase text-gray-900 [&>.table-row]:bg-gray-50">
                            {children}
                        </thead>
                    );
                },
                tr({ children }) {
                    return (
                        <tr className="table-row border-b odd:bg-white even:bg-gray-50">
                            {children}
                        </tr>
                    );
                },
                td({ children }) {
                    return <td className="px-6 py-3">{children}</td>;
                },
                th({ children }) {
                    return <th className="px-6 py-3">{children}</th>;
                },
            }}
        >
            {props.message}
        </ReactMarkdown>

    )
}
export default Response