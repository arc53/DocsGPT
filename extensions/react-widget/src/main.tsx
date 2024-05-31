import { createRoot } from 'react-dom/client';
import React from 'react';
import { DocsGPTWidget } from './components/DocsGPTWidget.tsx';

const rootElement = document.getElementById('docsgpt-widget-container') 

const {
    apiHost = 'https://gptcloud.arc53.com',
    selectDocs = 'default',
    apiKey = '82962c9a-aa77-4152-94e5-a4f84fd44c6a',
    avatar = 'https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png',
    title = 'Get AI assistance',
    description = 'DocsGPT\'s AI Chatbot is here to help',
    heroTitle = 'Welcome to DocsGPT !',
    heroDescription = 'This chatbot is built with DocsGPT and utilises GenAI, please review important information using sources.'
} = rootElement?.dataset as DOMStringMap;

const root = createRoot(rootElement as HTMLElement);

root.render(<DocsGPTWidget 
apiHost = {apiHost}
selectDocs = {selectDocs}
apiKey = {apiKey}
avatar = {avatar}
title = {title}
description = {description}
heroTitle = {heroTitle}
heroDescription = {heroDescription}/>);

