import {Query} from "../types/index"
import styled from 'styled-components';
import { ExternalLinkIcon } from '@radix-ui/react-icons'


const SourcesWrapper = styled.div`
margin: 4px;
display: flex;
flex-direction: column;
overflow: hidden;
`

const SourcesGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap:  0.5rem;
  max-width: 90vw;
  overflow-x: scroll;

  @media(min-width: 768px){
    max-width: 70vw;
  }
`

const SourceItem = styled.div`
cursor: pointer;
display: flex;
flex-direction: column;
justify-content: space-between;
border-radius: 6px;
background-color: ${props =>props.theme.secondary.bg};
 padding-left: 12px;
padding-right: 12px; 
color:${props => props.theme.text};
transform: background-color .2s, color .2s;

&:hover{
  background-color: ${props => props.theme.primary.bg};
  color: ${props => props.theme.primary.text};
}
`

const SourceLink = styled.div<{$hasExternalSource: boolean}>`
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.375rem;
  text-decoration: ${({$hasExternalSource}) => ($hasExternalSource? "underline": "none")};
  text-underline-offset: 2px;
`

const SourceLinkText = styled.p`
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.75rem;
  line-height: 1rem;
`

type TQuerySources = {
  sources:  Pick<Query, "sources">["sources"],
}

const QuerySources = ({sources}:TQuerySources) => {
  return (
    <SourcesWrapper>

      <SourcesGrid>
        {sources?.slice(0, 3)?.map((source, index) => (
          <SourceItem
            key={index}
          >
            <SourceLink
            $hasExternalSource={!!source.source && source.source !== "local"}
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
          </SourceItem>
        ))}
      </SourcesGrid>
    </SourcesWrapper>
  )
}

export default QuerySources