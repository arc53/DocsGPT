export default function Hero({ className = '' }: { className?: string }) {
  return (
    <div className="queryInfo rounded-lg text-jet">
      <div className={`flex flex-col ${className}`}>
        <p className="mb-3 ml-5 mr-5 mt-5 text-center leading-6 text-black-1000">
          Select the documentation you want to search from the{' '}
          <b>Source Docs</b> dropdown menu.
        </p>
        <p className="mb-5 ml-5 mr-5 text-center leading-6 text-black-1000">
          Enter a query into the input field below related to the information
          you are looking for. We will provide you with the most relevant
          answer!
        </p>
      </div>
    </div>
  );
}
