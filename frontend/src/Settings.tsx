import React from 'react';
import {
  Tabs,
  Tab,
  Select,
  SelectItem,
  SelectSection,
  Button,
  Modal,
  ModalContent,
  ModalHeader,
  ModalBody,
  ModalFooter,
  useDisclosure,
  Textarea,
  Table,
  TableHeader,
  TableColumn,
  TableBody,
  TableRow,
  TableCell,
  Image,
} from '@nextui-org/react';

export default function App() {
  const radiusList = ['full'];
  const [selectedKeys, setSelectedKeys] = React.useState(new Set(['text']));

  const selectedValue = React.useMemo(
    () => Array.from(selectedKeys).join(', ').replaceAll('_', ' '),
    [selectedKeys],
  );

  const { isOpen, onOpen, onOpenChange } = useDisclosure();
  const [selectedColor, setSelectedColor] = React.useState('default');

  return (
    <div className="inline-flex h-[120px] w-[529px] flex-col items-start justify-start gap-5 pb-2 pl-[69px] pt-[55px]">
      <div className="inline-flex items-center justify-end pt-[3.33px]">
        <div className="h-[45px] w-[189.06px] font-['Inter']  text-[40px] font-bold leading-[27px] text-neutral-800">
          Settings
        </div>
      </div>
      <div className="flex flex-wrap gap-4">
        {radiusList.map((radius) => (
          <Tabs key={radius} radius={radius} aria-label="Tabs radius">
            <Tab key="general" title="General">
              <div className="mt-6 font-['Inter'] text-lg font-semibold leading-none text-black">
                Select theme
              </div>
              <Select
                label="Theme"
                // placeholder="Select an animal"
                className="relative mt-4 h-[43.33px] w-[342px] max-w-xs"
              >
                <SelectSection showDivider title="Theme">
                  <SelectItem key="Light">Light</SelectItem>
                  <SelectItem key="Dark">Dark</SelectItem>
                </SelectSection>
              </Select>

              <div className="mt-10 font-['Inter'] text-lg font-semibold leading-none text-black">
                Select language
              </div>
              <Select
                label="Language"
                // placeholder="Select an animal"
                className="mt-4 max-w-xs"
              >
                <SelectSection showDivider title="language">
                  <SelectItem key="English(USA)">English(USA)</SelectItem>
                  <SelectItem key="French">French</SelectItem>
                </SelectSection>
              </Select>
            </Tab>

            <Tab key="prompt" title="Prompt">
              <div className="mt-6 inline-flex h-[17px] w-[197px] items-center justify-start pr-[73px]">
                <div className="font-['Inter'] text-lg font-semibold leading-none text-neutral-800">
                  Active Prompt
                </div>
              </div>
              <div className="align-center flex justify-center gap-6">
                <Select
                  className="mt-4 inline-flex h-[43.33px] w-[342px] max-w-xs items-center justify-center "
                  label="Prompt Dropdown..."
                >
                  <SelectItem key="Strict">Strict</SelectItem>
                </Select>
                <div>
                  <Button
                    className="mt-4 flex h-[42px] w-[101px] rounded-[62px] border border-violet-600 px-7 py-1.5"
                    color="secondary"
                    onPress={onOpen}
                  >
                    Add new
                  </Button>
                  <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
                    <ModalContent>
                      {(onClose) => (
                        <>
                          <ModalHeader className="flex flex-col gap-1">
                            Add Prompt
                            <div className="text-xs font-normal text-neutral-500">
                              Add your custom prompt and save it to DocsGPT.
                            </div>
                          </ModalHeader>
                          <ModalBody>
                            <Textarea
                              label="Prompt Name"
                              labelPlacement="outside"
                              placeholder="Enter your Prompt Name"
                              className="max-w-xs"
                            />
                            <Textarea
                              label="Prompt Text"
                              labelPlacement="outside"
                              // placeholder="Enter your Prompt Name"
                              className="max-w-xs"
                            />
                          </ModalBody>
                          <ModalFooter>
                            <Button
                              color="danger"
                              variant="light"
                              onPress={onClose}
                            >
                              Close
                            </Button>
                            <Button color="secondary" onPress={onClose}>
                              Save
                            </Button>
                          </ModalFooter>
                        </>
                      )}
                    </ModalContent>
                  </Modal>
                </div>
              </div>
            </Tab>
            <Tab key="documents" title="Documents">
              <div className="flex flex-col gap-3">
                <Table
                  color="secondarys"
                  selectionMode="single"
                  defaultSelectedKeys={['2']}
                  aria-label="Example static collection table"
                >
                  <TableHeader>
                    <TableColumn>Document Name</TableColumn>
                    <TableColumn>Vector Date</TableColumn>
                    <TableColumn>Vector Name</TableColumn>
                  </TableHeader>
                  <TableBody>
                    <TableRow key="1">
                      <TableCell>Base</TableCell>
                      <TableCell>2001</TableCell>
                      <TableCell>#A1BC</TableCell>
                    </TableRow>
                    <TableRow key="2">
                      <TableCell>ABC</TableCell>
                      <TableCell>2011</TableCell>
                      <TableCell>#A2BC</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </div>
              <div>
                <Button
                  className="left-[270px] mt-4"
                  color="secondary"
                  onPress={onOpen}
                >
                  Add new
                </Button>
                <Modal isOpen={isOpen} onOpenChange={onOpenChange}>
                  <ModalContent>
                    {(onClose) => (
                      <>
                        <ModalHeader className="flex flex-col gap-1">
                          Upload New Documentation
                          <div className="text-xs font-normal text-neutral-500 ">
                            Please upload .pdf, .txt, .rst, .docx, .md, .zip
                            limited to 25mb
                          </div>
                        </ModalHeader>
                        <ModalBody>
                          <Textarea
                            label="Name"
                            labelPlacement="outside"
                            placeholder="Enter Name"
                            className="max-w-xs"
                          />
                          <Textarea
                            // label="URL"
                            labelPlacement="outside"
                            placeholder="URL (Optional)"
                            className="max-w-xs"
                          />
                        </ModalBody>
                        <ModalFooter>
                          <Button
                            color="danger"
                            variant="light"
                            onPress={onClose}
                          >
                            Back
                          </Button>
                          <Button color="secondary" onPress={onClose}>
                            Train
                          </Button>
                        </ModalFooter>
                      </>
                    )}
                  </ModalContent>
                </Modal>
              </div>
            </Tab>
            <Tab key="widgets" title="Widgets">
              <div className="mt-6 font-['Inter'] text-lg font-semibold leading-none text-neutral-800">
                Widget source
              </div>
              <Select
                className="mt-5 inline-flex h-[43.33px] w-[342px] max-w-xs items-center justify-center "
                label="Select widget source"
              >
                {/* <SelectItem key="Strict">Strict</SelectItem> */}
              </Select>
              <div className="mt-[24px] font-['Inter'] text-lg font-semibold leading-none text-neutral-800">
                Widget method
              </div>
              <Select
                className="mt-5 inline-flex h-[43.33px] w-[342px] max-w-xs items-center justify-center "
                label="Select widget method"
              >
                {/* <SelectItem key="Strict">Strict</SelectItem> */}
              </Select>
              <div className="mt-[24px] font-['Inter'] text-lg font-semibold leading-none text-neutral-800">
                Widget type
              </div>
              <Select
                className="mt-5 inline-flex h-[43.33px] w-[342px] max-w-xs items-center justify-center "
                label="Select widget type"
              >
                {/* <SelectItem key="Strict">Strict</SelectItem> */}
              </Select>
              <Textarea
                label="Widget Code Snippet"
                labelPlacement="outside"
                placeholder="Widget code... along with some snippets"
                className="mt-7 max-w-xs"
              />
              <div className="flex flex-col gap-[16px]">
                <div className="mt-7 font-['Inter'] text-lg font-semibold leading-none text-neutral-800">
                  Widget screenshot
                </div>
                <Image
                  isBlurred
                  width={240}
                  src="https://nextui-docs-v2.vercel.app/images/album-cover.png"
                  alt="NextUI Album Cover"
                  classNames="m-5"
                />
              </div>
            </Tab>
          </Tabs>
        ))}
      </div>
    </div>
  );
}
