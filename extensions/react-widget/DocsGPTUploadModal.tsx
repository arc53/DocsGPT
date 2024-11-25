import React, {useState} from 'react';
import {Modal, Button, TextField} from '@material-ui/core';

type DocsGPTUploadModalProps = {
	open: boolean,
	onClose: () => void;
	onSubmit: (data: string) => void;
};

export const DocsGPTUpload = ({
	open,
	onClose,
	onSubmit,
}: DocsGPTUploadModalProps) => {
	const [data, setData] = useState('');

	const handleSubmit = () => {
		onSubmit(data);
		onClose();
	};

return (
	<Modal open={open} onClose={onClose}>
		<div style={{padding: '20px', backgroundColor: 'white'}}>
			<h2> Upload to DocsGPT </h2>
			<TextField label='Data' multilinerows={4}, variant="outlined",fullWidthValue={data}, onChange={(e => setData(e.target.value)} />
			<button onClick={handleSubmit} color="primary" variant="contained">
				Submit
			</button>
		</div>
	</Modal>

    );
);
