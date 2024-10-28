import React, { useState } from 'react';
import {Query, THEME} from "../types/index"
import styled from 'styled-components';
import { ExternalLinkIcon, FileTextIcon } from '@radix-ui/react-icons'


const SourcesWrapper = styled.div`
margin-bottom: 1rem;
display: flex;
flex-direction: column;
overflow: hidden;
`

const SourcesHeader = styled.div`
  margin: 0.5rem 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
`

const SourcesTitle = styled.p`
  font-size: 1rem;
  font-weight: 600;
  color: ${props => props.theme.text};
`

const SourcesGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap:  0.5rem;
  margin-left: 0.75rem;
  margin-right: 1.25rem;
  max-width: 90vw;
  overflow-x: scroll;

  @media(min-width: 768px){
    max-width: 70vw;
  }
`

const SourceItem = styled.div`
height: 7rem; 
cursor: pointer;
display: flex;
flex-direction: column;
justify-content: space-between;
border-radius: 1.25rem;
background-color: ${props =>props.theme.secondary.bg};
padding: 1rem; 
color:${props => props.theme.text};
transform: background-color .2s, color .2s;

&:hover{
  background-color: ${props => props.theme.primary.bg};
  color: ${props => props.theme.primary.text};
}
`

const SourceText = styled.p`
  height: 3rem;
  overflow: hidden;
  text-overflow: ellipsis;
font-size:  0.75rem;
line-height: 1rem;
color: ${props => props.theme.text};
`

const SourceLink = styled.div`
  margin-top: 0.875rem;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.375rem;
  text-decoration: underline;
  text-underline-offset: 2px;
`

const SourceLinkText = styled.p`
  margin-top: 0.125rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.75rem;
  line-height: 1rem;
`

const Tooltip = styled.div`
  position: absolute;
  left: 50%;
  z-index: 30;
  max-height: 12rem;
  width: 10rem;
  transform: translateX(-50%) translateY(3px);
  border-radius: 0.75rem;
  background-color: ${props => props.theme.bg};
  padding: 1rem;
  color: ${props => props.theme.text};
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);

  @media (min-width: 640px) {
    width: 14rem;
  }
`

const TooltipText = styled.p`
  max-height: 10.25rem;
  overflow-y: auto;
  word-break: break-word;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  line-height: 1.25rem;
`

type TQuerySources = {
  sources:  Pick<Query, "sources">["sources"],
  theme?: THEME
}

const QuerySources = ({sources, theme}:TQuerySources) => {
  const [activeTooltip, setActiveTooltip] = useState<number | null>(null)

  return (
    <SourcesWrapper>
      <SourcesHeader>
      <FileTextIcon width={24} height={24} color={`${theme === 'light' ? "#000" : "#fff"}`}/>
        <SourcesTitle>Sources</SourcesTitle>
      </SourcesHeader>

      <SourcesGrid>
        {sources?.slice(0, 3)?.map((source, index) => (
          <SourceItem
            key={index}
            onMouseEnter={() => setActiveTooltip(index)}
            onMouseLeave={() => setActiveTooltip(null)}
          >
            <SourceText>{source.text}</SourceText>
            <SourceLink
              onClick={() =>
                source.source && source.source !== 'local'
                  ? window.open(source.source, '_blank', 'noopener,noreferrer')
                  : null
              }
            >
              <ExternalLinkIcon />
              <SourceLinkText title={source.source && source.source !== 'local' ? source.source : source.title}>
                {source.source && source.source !== 'local' ? source.source : source.title}
              </SourceLinkText>
            </SourceLink>
            {activeTooltip === index && (
              <Tooltip
                onMouseEnter={() => setActiveTooltip(index)}
                onMouseLeave={() => setActiveTooltip(null)}
              >
                <TooltipText>
                  {source.text}
                </TooltipText>
              </Tooltip>
            )}
          </SourceItem>
        ))}
      </SourcesGrid>
    </SourcesWrapper>
  )
}

export default QuerySources