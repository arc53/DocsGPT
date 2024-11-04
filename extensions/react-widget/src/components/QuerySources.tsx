import {Query, THEME} from "../types/index"
import styled from 'styled-components';
import { ExternalLinkIcon, FileTextIcon } from '@radix-ui/react-icons'


const SourcesWrapper = styled.div`
padding: 12px;
margin-left: 4px;
margin-bottom: 0.75rem;
display: flex;
flex-direction: column;
overflow: hidden;
`

const SourcesHeader = styled.div`
  margin: 0.3rem 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
`

const SourcesTitle = styled.p`
  font-size: 0.75rem;
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

const SourceLink = styled.div`
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 0.375rem;
  text-decoration: underline;
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
  theme?: THEME
}

const QuerySources = ({sources, theme}:TQuerySources) => {
  return (
    <SourcesWrapper>
      <SourcesHeader>
      <FileTextIcon width={15} height={15} color={`${theme === 'light' ? "#000" : "#fff"}`}/>
        <SourcesTitle>Sources</SourcesTitle>
      </SourcesHeader>

      <SourcesGrid>
        {sources?.slice(0, 3)?.map((source, index) => (
          <SourceItem
            key={index}
          >
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
          </SourceItem>
        ))}
      </SourcesGrid>
    </SourcesWrapper>
  )
}

export default QuerySources